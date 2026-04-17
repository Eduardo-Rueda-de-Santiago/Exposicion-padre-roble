import machine
import neopixel

DEFAULT_LED_PIN = 21
DEFAULT_LED_NUMBER = 200


class LedStripController:
    """
    Controls a NeoPixel LED strip and maps distance measurements
    to brightness levels using linear interpolation.
    """

    def __init__(
        self,
        pin: int = DEFAULT_LED_PIN,
        led_num: int = DEFAULT_LED_NUMBER,
        min_distance_expected: int = 50,
        max_distance_expected: int = 250,
        min_brightness: int = 0,
        max_brightness: int = 255,
    ) -> None:
        """
        Initialize LED strip controller.

        Args:
            pin: GPIO pin connected to the LED strip.
            led_num: Number of LEDs in the strip.
            min_distance_expected: Distance for maximum brightness.
            max_distance_expected: Distance for minimum brightness.
            min_brightness: Minimum brightness value.
            max_brightness: Maximum brightness value.
        """
        self.led_strip = neopixel.NeoPixel(machine.Pin(pin), led_num)

        self.current_led_brightness = 0
        self.target_led_brightness = 0

        self._min_distance_expected = min_distance_expected
        self._max_distance_expected = max_distance_expected
        self._min_brightness = min_brightness
        self._max_brightness = max_brightness

    def _set_led_brightness(self) -> None:
        """
        Apply the current target brightness to all LEDs in the strip.
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
        Convert distance into a target LED brightness value.

        Mapping rules:
        - distance >= max_distance_expected → min_brightness
        - distance <= min_distance_expected → max_brightness
        - linear interpolation in between
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

    # ───────────────────────── GETTERS ─────────────────────────

    def get_min_distance_expected(self) -> int:
        """Return minimum distance threshold for max brightness."""
        return self._min_distance_expected

    def get_max_distance_expected(self) -> int:
        """Return maximum distance threshold for min brightness."""
        return self._max_distance_expected

    def get_min_brightness(self) -> int:
        """Return configured minimum brightness."""
        return self._min_brightness

    def get_max_brightness(self) -> int:
        """Return configured maximum brightness."""
        return self._max_brightness

    def get_current_led_brightness(self) -> int:
        """Return currently applied LED brightness."""
        return self.current_led_brightness

    def get_target_led_brightness(self) -> int:
        """Return computed target LED brightness before applying."""
        return self.target_led_brightness

    def get_led_count(self) -> int:
        """Return number of LEDs in the strip."""
        return len(self.led_strip)

    # ───────────────────────── HELPERS ─────────────────────────

    def bound_brightness(self, brightness: int) -> int:
        """
        Clamp brightness into valid PWM range (0–255).

        Args:
            brightness: Input brightness value.

        Returns:
            Clamped brightness value.
        """
        if brightness > 255:
            return 255
        if brightness < 0:
            return 0
        return brightness

    def update_led_brightness(self, distance_to_person: int) -> None:
        """
        Update brightness based on distance and apply it to LEDs.

        Args:
            distance_to_person: Measured distance in cm.
        """
        self._calculate_led_brightness(distance_to_person)
        self._set_led_brightness()

    def set_min_brightness(self, min_brightness: int) -> None:
        """
        Set minimum brightness value (clamped to valid range).

        Args:
            min_brightness: New minimum brightness.
        """
        if min_brightness is not None:
            self._min_brightness = self.bound_brightness(min_brightness)

    def set_max_brightness(self, max_brightness: int) -> None:
        """
        Set maximum brightness value (clamped to valid range).

        Args:
            max_brightness: New maximum brightness.
        """
        if max_brightness is not None:
            self._max_brightness = self.bound_brightness(max_brightness)

    def set_min_distance_expected(self, min_distance_expected: int):
        """
        Set minimum distance expected.

        Args:
            min_distance_expected: New min distance expected
        """
        if min_distance_expected is not None:
            self._min_distance_expected = min_distance_expected

    def set_max_distance_expected(self, max_distance_expected: int):
        """
        Set maximum distance expected
        Args:
            max_distance_expected: New maximum distance expected
        """
        if max_distance_expected is not None:
            self._max_distance_expected = max_distance_expected
