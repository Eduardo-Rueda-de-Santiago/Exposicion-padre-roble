import machine
import neopixel
import uasyncio as asyncio
from common_data_storage import DataStorage

DEFAULT_LED_PIN = 21
DEFAULT_LED_NUMBER = 200

# How often the LED task checks shared storage for a new distance (ms).
# 0 = yield once to scheduler then immediately retry (maximum responsiveness).
DEFAULT_LED_UPDATE_INTERVAL_MS = 0


class LedStripController:
    """
    Controls a NeoPixel LED strip and maps distance measurements
    (read from a shared DataStorage) to brightness levels using
    linear interpolation.

    Brightness mapping:
        distance <= min_distance_expected  →  max_brightness
        distance >= max_distance_expected  →  min_brightness
        in between                         →  linear interpolation

    LED config (min/max brightness, min/max distance) can be updated at
    runtime by the BLE task via DataStorage.queue_led_config().  The LED
    task drains the pending config at the top of every loop iteration.
    """

    def __init__(
        self,
        common_data_storage: DataStorage,
        pin: int = DEFAULT_LED_PIN,
        led_num: int = DEFAULT_LED_NUMBER,
        min_distance_expected: int = 50,
        max_distance_expected: int = 250,
        min_brightness: int = 10,
        max_brightness: int = 255,
    ) -> None:
        """
        Initialize LED strip controller.

        Args:
            common_data_storage:   Shared storage — distance is read from here,
                                   pending BLE config is drained here.
            pin:                   GPIO pin connected to the LED strip data line.
            led_num:               Number of LEDs in the strip.
            min_distance_expected: Distance (cm) that maps to max brightness.
            max_distance_expected: Distance (cm) that maps to min brightness.
            min_brightness:        Minimum brightness value (0–255).
            max_brightness:        Maximum brightness value (0–255).
        """
        self.led_strip = neopixel.NeoPixel(machine.Pin(pin), led_num)
        self.common_data_storage = common_data_storage

        self.current_led_brightness: int = min_brightness
        self.target_led_brightness: int = min_brightness

        self._min_distance_expected = min_distance_expected
        self._max_distance_expected = max_distance_expected
        self._min_brightness = min_brightness
        self._max_brightness = max_brightness

    # ───────────────────────── Config application ─────────────────────────

    def _apply_pending_config(self) -> None:
        """
        Drain any LED config queued by the BLE task and apply it.

        Called at the top of every run_led_async loop iteration.
        DataStorage.pop_led_config() returns None when nothing is pending,
        making this a cheap no-op in the common case.

        Accepted config keys → setter called:
            "min_b"  →  set_min_brightness
            "max_b"  →  set_max_brightness
            "min_d"  →  set_min_distance_expected
            "max_d"  →  set_max_distance_expected
        """
        cfg = self.common_data_storage.pop_led_config()
        if cfg is None:
            return

        for key, setter_name in DataStorage.CONFIG_KEY_MAP.items():
            if key in cfg:
                try:
                    getattr(self, setter_name)(int(cfg[key]))
                except Exception as e:
                    print("[LED] Bad config value for '{}': {}".format(key, e))

        print("[LED] Config applied:", cfg)

    # ───────────────────────── Internal update logic ─────────────────────────

    def _set_led_brightness(self) -> None:
        """
        Apply target_led_brightness to every LED in the strip and push
        the update over the data wire.
        """
        self.current_led_brightness = self.target_led_brightness

        for i in range(len(self.led_strip)):
            self.led_strip[i] = (
                self.current_led_brightness,
                self.current_led_brightness,
                self.current_led_brightness,
            )

        self.led_strip.write()

    def _calculate_led_brightness(self, distance_to_person: int) -> None:
        """
        Convert a distance measurement into a target brightness value and
        store it in self.target_led_brightness.

        Args:
            distance_to_person: Measured distance in cm.
        """
        if distance_to_person is None:
            return

        if distance_to_person >= self._max_distance_expected:
            self.target_led_brightness = self._min_brightness
            return

        if distance_to_person <= self._min_distance_expected:
            self.target_led_brightness = self._max_brightness
            return

        ratio = (self._max_distance_expected - distance_to_person) / (
            self._max_distance_expected - self._min_distance_expected
        )

        brightness = self._min_brightness + ratio * (
            self._max_brightness - self._min_brightness
        )

        self.target_led_brightness = self.bound_brightness(int(brightness))

    # ───────────────────────── Async entry point ─────────────────────────

    async def run_led_async(
        self, update_interval_ms: int = DEFAULT_LED_UPDATE_INTERVAL_MS
    ) -> None:
        """
        Async task entry point.

        Each iteration:
          1. Drain and apply any pending BLE config from DataStorage.
          2. Read the latest distance from DataStorage.
          3. Recalculate target brightness.
          4. Write to the strip only if brightness changed (NeoPixel.write()
             is slow — skipping unchanged frames keeps 0 ms sleep cheap).

        Args:
            update_interval_ms: Delay between refresh cycles (ms).
                                 0 = yield-then-immediately-retry for maximum
                                 LED responsiveness (recommended when the sensor
                                 task uses a longer sleep interval).
        """
        while True:
            # 1. Apply any config pushed by the BLE task
            self._apply_pending_config()

            # 2 & 3. Read distance and recalculate target brightness
            distance = self.common_data_storage.distance_to_person
            self._calculate_led_brightness(distance)

            # 4. Only push to strip when brightness actually changed
            if self.target_led_brightness != self.current_led_brightness:
                self._set_led_brightness()

            await asyncio.sleep_ms(update_interval_ms)

    # ───────────────────────── Getters ─────────────────────────

    def get_min_distance_expected(self) -> int:
        """Return minimum distance threshold (maps to max brightness)."""
        return self._min_distance_expected

    def get_max_distance_expected(self) -> int:
        """Return maximum distance threshold (maps to min brightness)."""
        return self._max_distance_expected

    def get_min_brightness(self) -> int:
        """Return configured minimum brightness."""
        return self._min_brightness

    def get_max_brightness(self) -> int:
        """Return configured maximum brightness."""
        return self._max_brightness

    def get_current_led_brightness(self) -> int:
        """Return the brightness value currently applied to the strip."""
        return self.current_led_brightness

    def get_target_led_brightness(self) -> int:
        """Return the computed target brightness (before the next write)."""
        return self.target_led_brightness

    def get_led_count(self) -> int:
        """Return the number of LEDs in the strip."""
        return len(self.led_strip)

    # ───────────────────────── Setters ─────────────────────────

    def bound_brightness(self, brightness: int) -> int:
        """
        Clamp a brightness value to the valid 0–255 PWM range.

        Args:
            brightness: Raw brightness value.

        Returns:
            Clamped value in [0, 255].
        """
        if brightness > 255:
            return 255
        if brightness < 0:
            return 0
        return brightness

    def set_min_brightness(self, min_brightness: int) -> None:
        """
        Update the minimum brightness limit (clamped to 0–255).

        Args:
            min_brightness: New minimum brightness.
        """
        if min_brightness is not None:
            self._min_brightness = self.bound_brightness(min_brightness)

    def set_max_brightness(self, max_brightness: int) -> None:
        """
        Update the maximum brightness limit (clamped to 0–255).

        Args:
            max_brightness: New maximum brightness.
        """
        if max_brightness is not None:
            self._max_brightness = self.bound_brightness(max_brightness)

    def set_min_distance_expected(self, min_distance_expected: int) -> None:
        """
        Update the minimum distance threshold.

        Args:
            min_distance_expected: New minimum distance (cm).
        """
        if min_distance_expected is not None:
            self._min_distance_expected = min_distance_expected

    def set_max_distance_expected(self, max_distance_expected: int) -> None:
        """
        Update the maximum distance threshold.

        Args:
            max_distance_expected: New maximum distance (cm).
        """
        if max_distance_expected is not None:
            self._max_distance_expected = max_distance_expected
