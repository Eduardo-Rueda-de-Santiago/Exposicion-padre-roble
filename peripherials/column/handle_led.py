import machine
import neopixel
import uasyncio as asyncio
from common_data_storage import DataStorage

DEFAULT_LED_PIN = 21
DEFAULT_LED_NUMBER = 200

# How often the LED task checks the shared storage for a new distance (ms)
DEFAULT_LED_UPDATE_INTERVAL_MS = 10


class LedStripController:
    """
    Controls a NeoPixel LED strip and maps distance measurements
    (read from a shared DataStorage) to brightness levels using
    linear interpolation.

    Brightness mapping:
        distance <= min_distance_expected  →  max_brightness
        distance >= max_distance_expected  →  min_brightness
        in between                         →  linear interpolation
    """

    def __init__(
        self,
        common_data_storage: DataStorage,
        pin: int = DEFAULT_LED_PIN,
        led_num: int = DEFAULT_LED_NUMBER,
        min_distance_expected: int = 20,
        max_distance_expected: int = 150,
        min_brightness: int = 0,
        max_brightness: int = 255,
    ) -> None:
        """
        Initialize LED strip controller.

        Args:
            common_data_storage: Shared storage from which the distance is read.
            pin: GPIO pin connected to the LED strip data line.
            led_num: Number of LEDs in the strip.
            min_distance_expected: Distance (cm) that maps to max brightness.
            max_distance_expected: Distance (cm) that maps to min brightness.
            min_brightness: Minimum brightness value (0–255).
            max_brightness: Maximum brightness value (0–255).
        """
        self.led_strip = neopixel.NeoPixel(machine.Pin(pin), led_num)
        self.common_data_storage = common_data_storage

        self.current_led_brightness: int = 0
        self.target_led_brightness: int = 0

        self._min_distance_expected = min_distance_expected
        self._max_distance_expected = max_distance_expected
        self._min_brightness = min_brightness
        self._max_brightness = max_brightness

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

    def update_led_brightness(self, distance_to_person: int) -> None:
        """
        Compute brightness from distance and immediately apply it to the strip.

        Args:
            distance_to_person: Measured distance in cm.
        """
        self._calculate_led_brightness(distance_to_person)
        self._set_led_brightness()

    # ───────────────────────── Async entry point ─────────────────────────

    async def run_led_async(
        self, update_interval_ms: int = DEFAULT_LED_UPDATE_INTERVAL_MS
    ) -> None:
        """
        Async task entry point.

        Loops forever, reading the latest distance from shared storage
        and updating the LED strip accordingly.  The await gives the
        sensor coroutine (and any other tasks) CPU time between updates.

        Args:
            update_interval_ms: Delay between LED refresh cycles (ms).
        """
        while True:
            distance = self.common_data_storage.distance_to_person
            self.update_led_brightness(distance)
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
