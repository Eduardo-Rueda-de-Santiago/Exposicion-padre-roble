import time

import machine
import neopixel

NUM_LEDS = 34
HALF = NUM_LEDS // 2
PINK = (255, 20, 147)
GREEN = (10, 128, 0)


neopixel_led = neopixel.NeoPixel(machine.Pin(21), NUM_LEDS)

move_offset = 0
bright_offset = 0


def scale_color(color, brightness):
    return tuple(int(c * brightness / 255) for c in color)


def set_wave_colors(led, wave_init, wave_end, color):
    length = abs(wave_end - wave_init)
    if length == 0:
        led[wave_init] = color
        return

    step = 1 if wave_end > wave_init else -1

    for idx, i in enumerate(range(wave_init, wave_end + step, step)):
        progress = idx / length  # 0 → 1

        # Make the END of the wave the brightest (toward center)
        brightness = int(progress * 150)

        led[i] = scale_color(color, brightness)


move_offset = 0


while True:
    neopixel_led.fill((0, 0, 0))

    # Left wave: from 0 → center
    left_end = min(move_offset, HALF)
    set_wave_colors(neopixel_led, 0, left_end, PINK)

    # Right wave: from last → center
    right_end = max(NUM_LEDS - 1 - move_offset, HALF) - 1
    set_wave_colors(neopixel_led, NUM_LEDS - 1, right_end, GREEN)

    neopixel_led.write()

    move_offset += 1
    if move_offset > HALF:
        move_offset = 0

    time.sleep_ms(100)
