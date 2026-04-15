"""
Waveshare HMMD mmWave Sensor + NeoPixel strip
MicroPython for ESP32

WIRING
──────────────────────────────────────────────
HMMD Sensor  →  ESP32
  Pin 1 (3.3V) → 3.3V
  Pin 2 (GND)  → GND
  Pin 3 (TX)   → GPIO16  (UART2 RX on ESP32)
  Pin 4 (RX)   → GPIO17  (UART2 TX on ESP32)
  Pin 5 (OT2)  → optional GPIO18 (HIGH = presence)

NeoPixel strip → ESP32
  DIN          → GPIO6   ← same pin as original
  5V / VCC     → 5V (Vin)
  GND          → GND

NOTE: The sensor operates at 3.3 V logic — no level
      shifting needed when connected to an ESP32.
──────────────────────────────────────────────
"""

import time

import machine
import neopixel

# ── Pin / hardware config ──────────────────────────────────────────────────────
UART_ID = 2  # Hardware UART2
UART_RX = 16  # Sensor TX → ESP32 GPIO16
UART_TX = 17  # Sensor RX → ESP32 GPIO17
BAUD_RATE = 115200

NEO_PIN = 5  # NeoPixel data pin
NUMPIXELS = 34
BRIGHTNESS = 1.0  # 0.0 – 1.0  (MicroPython neopixel has no built-in
# setBrightness, so we scale colours manually)

DISTANCE_THRESHOLD = 150  # cm — LEDs turn on when target is closer than this

# ── Init command (same hex string as the Arduino sketch) ──────────────────────
INIT_HEX = "FDFCFBFA0800120000006400000004030201"

# ── Hardware init ─────────────────────────────────────────────────────────────
uart = machine.UART(
    UART_ID, baudrate=BAUD_RATE, rx=UART_RX, tx=UART_TX, bits=8, parity=None, stop=1
)

np = neopixel.NeoPixel(machine.Pin(NEO_PIN), NUMPIXELS)


# ── Helpers ───────────────────────────────────────────────────────────────────
def scale_color(r, g, b):
    """Apply global brightness scaling."""
    return (int(r * BRIGHTNESS), int(g * BRIGHTNESS), int(b * BRIGHTNESS))


def pixels_fill(color):
    for i in range(NUMPIXELS):
        np[i] = color
    np.write()


def pixels_clear():
    pixels_fill((0, 0, 0))


def send_hex_data(hex_string):
    """Convert a hex string to bytes and send over UART."""
    data = bytes(int(hex_string[i : i + 2], 16) for i in range(0, len(hex_string), 2))
    uart.write(data)


def process_line(line):
    print("Packet:", line)

    if line.startswith("Range "):
        try:
            distance = int(line[6:])
        except ValueError:
            return

        print(f"Distance: {distance} cm")

        if distance <= DISTANCE_THRESHOLD:
            pixels_fill(scale_color(255, 255, 255))
        else:
            pixels_clear()

    elif line == "ON":
        print("Presence detected!")


# ── Main ──────────────────────────────────────────────────────────────────────
errs = 0


def main():
    # Clear strip on start
    pixels_clear()
    print("Serial up!")

    # Send init command to radar
    send_hex_data(INIT_HEX)

    incoming = b""

    while True:
        if uart.any():
            chunk = uart.read(uart.any())
            if chunk:
                incoming += chunk

                # Process complete lines
                while b"\n" in incoming:
                    idx = incoming.index(b"\n")
                    raw_line = incoming[:idx]
                    incoming = incoming[idx + 1 :]
                    try:
                        # Strip carriage return if present
                        line = raw_line.decode("ascii", "ignore").strip("\r")
                        if line:
                            process_line(line)
                    except Exception as e:
                        global errs
                        errs += 1
                        print(f"Error procesing line, errors: {errs}")
        time.sleep_ms(10)  # small yield to avoid busy-spin


time.sleep_ms(500)  # Settle after Thonny reset
main()
