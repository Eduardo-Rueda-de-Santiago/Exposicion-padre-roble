"""
Waveshare HMMD mmWave Sensor
MicroPython for ESP32

WIRING
──────────────────────────────────────────────
HMMD Sensor  →  ESP32
  Pin 1 (3.3V) → 3.3V
  Pin 2 (GND)  → GND
  Pin 3 (TX)   → GPIO16  (UART2 RX on ESP32)
  Pin 4 (RX)   → GPIO17  (UART2 TX on ESP32)

NOTE: The sensor operates at 3.3 V logic — no level
      shifting needed when connected to an ESP32.
──────────────────────────────────────────────
"""

import machine

BAUD_RATE = 115200
DEFAULT_UART_ID = 2
DEFAULT_UART_RX = 16  # Sensor TX → ESP32 GPIO16
DEFAULT_UART_TX = 17  # Sensor RX → ESP32 GPIO17

# ── Init command ──────────────────────
INIT_HEX = "FDFCFBFA0800120000006400000004030201"


class MotionSensor:
    def __init__(
        self,
        uart_id: int = DEFAULT_UART_ID,
        uart_rx_pin: int = DEFAULT_UART_RX,
        uart_tx_pin: int = DEFAULT_UART_TX,
        sensor_reading_wait_ms: int = 10,
    ) -> None:
        self.uart = machine.UART(
            uart_id,
            baudrate=BAUD_RATE,
            rx=uart_rx_pin,
            tx=uart_tx_pin,
            bits=8,
            parity=None,
            stop=1,
        )
        self.sensor_reading_wait_ms = sensor_reading_wait_ms
        self.incoming = b""
        self.continuous_fails = 0
        self.last_distance = 999

    def _send_hex_data(self, hex_string):
        data = bytes(
            int(hex_string[i : i + 2], 16) for i in range(0, len(hex_string), 2)
        )
        self.uart.write(data)

    def _set_sensor_normal_reading_mode(self):
        self._send_hex_data(INIT_HEX)

    def _read_sensor_data(self):
        if self.uart.any():
            chunk = self.uart.read(self.uart.any())
            if chunk:
                self.incoming += chunk
                while b"\n" in self.incoming:
                    idx = self.incoming.index(b"\n")
                    raw_line = self.incoming[:idx]
                    self.incoming = self.incoming[idx + 1 :]
                    decoded_line = self._decode_sensor_data(raw_line)
                    return self._extract_distance_from_line(decoded_line)

    def _decode_sensor_data(self, raw_line) -> str:
        try:
            line: str = raw_line.decode("ascii", "ignore").strip("\r")
            if line:
                return line
            return ""

        except Exception as e:
            raise Exception("No data read")

    def _extract_distance_from_line(self, processed_line: str) -> int:
        if processed_line.startswith("Range "):
            try:
                return int(processed_line[6:])
            except ValueError as e:
                raise e

        return -1

    def run_sensor(self):
        self._set_sensor_normal_reading_mode()

        while True:
            try:
                self.last_distance = self._read_sensor_data()
            except Exception as e:
                self.continuous_fails += 1
                if self.continuous_fails == 5:
                    self._set_sensor_normal_reading_mode()

                elif self.continuous_fails > 10:
                    ## TODO: Notify via bluethoot
                    pass

            finally:
                time.sleep_ms(self.sensor_reading_wait_ms)
