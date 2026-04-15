import machine
import neopixel

DEFAULT_LED_PIN = 21
DEFAULT_LED_NUMBER = 200


class LedStripController:
    def __init__(
        self,
        pin: int = DEFAULT_LED_PIN,
        led_num: int = DEFAULT_LED_NUMBER,
        min_distance_expected=50,
        max_distance_expected=250,
    ) -> None:
        self.led_strip = neopixel.NeoPixel(machine.Pin(21), led_num)
        self.led_brightness = 0

    def _set_led_brightness(self) -> None:
        pass

    def _calculate_led_brightness(self, distance_to_person) -> None:
        pass

    def update_led_brightness(self, distance_to_person) -> None:
        self._calculate_led_brightness(distance_to_person)
        self._set_led_brightness()
