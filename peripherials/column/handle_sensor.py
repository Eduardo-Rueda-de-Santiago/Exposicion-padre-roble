"""
Waveshare HMMD mmWave Sensor
MicroPython for ESP32

Sensor wiki:
    https://www.waveshare.com/wiki/HMMD_mmWave_Sensor

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
import uasyncio as asyncio

# UART communication settings
BAUD_RATE = 115200
DEFAULT_UART_ID = 2

# Default GPIO pin mapping (ESP32 UART2)
DEFAULT_UART_RX = 16  # Sensor TX → ESP32 GPIO16
DEFAULT_UART_TX = 17  # Sensor RX → ESP32 GPIO17

# ── Sensor initialization command (hex string) ──────────────────────
# This command switches the HMMD sensor into "normal reading mode"
# as defined in the official communication protocol documentation.
INIT_HEX = "FDFCFBFA0800120000006400000004030201"


class MotionSensor:
    """
    Interface class for the Waveshare HMMD mmWave motion sensor.

    Responsibilities:
    - Initialize UART communication
    - Send configuration commands to the sensor
    - Read and parse incoming sensor data
    - Extract distance measurements from sensor output
    """

    def __init__(
        self,
        uart_id: int = DEFAULT_UART_ID,
        uart_rx_pin: int = DEFAULT_UART_RX,
        uart_tx_pin: int = DEFAULT_UART_TX,
        sensor_reading_wait_ms: int = 10,
    ) -> None:
        """
        Initialize UART communication and internal state.

        Args:
            uart_id: UART interface ID (ESP32 typically uses UART2)
            uart_rx_pin: GPIO pin for UART RX (connected to sensor TX)
            uart_tx_pin: GPIO pin for UART TX (connected to sensor RX)
            sensor_reading_wait_ms: Delay between read attempts
        """

        # Configure UART interface
        self.uart = machine.UART(
            uart_id,
            baudrate=BAUD_RATE,
            rx=uart_rx_pin,
            tx=uart_tx_pin,
            bits=8,
            parity=None,
            stop=1,
        )

        # Delay between polling cycles (ms)
        self.sensor_reading_wait_ms = sensor_reading_wait_ms

        # Buffer for accumulating incoming UART data
        self.incoming = bytearray()

        # Counter for consecutive read failures
        self.continuous_fails = 0

        # Last successfully read distance value (default large value)
        self.last_distance = 999

    def _send_hex_data(self, hex_string):
        """
        Convert a hexadecimal string into raw bytes and send it over UART.

        Args:
            hex_string: String representing hex bytes (e.g. "FDFCFBFA...")
        """

        # Convert hex string into bytes
        data = bytes.fromhex(hex_string)

        # Send bytes through UART
        self.uart.write(data)

    def _set_sensor_normal_reading_mode(self):
        """
        Send initialization command to the sensor to enable
        continuous measurement mode.
        """
        self._send_hex_data(INIT_HEX)

    def _read_sensor_data(self):
        """
        Read incoming UART data, process complete lines,
        and extract distance measurements.

        Returns:
            int: Distance value in sensor units
                 None if no valid data found
        """

        # Check if data is available in UART buffer
        n = self.uart.any()
        if n:
            chunk = self.uart.read(n)
            if not chunk:
                return None

            if chunk:
                # Append new data to internal buffer
                self.incoming += chunk

                # Process complete lines (terminated by newline)
                while b"\n" in self.incoming:
                    idx = self.incoming.index(b"\n")

                    # Extract one line from buffer
                    raw_line = self.incoming[:idx]
                    if not raw_line:
                        self.incoming = self.incoming[idx + 1 :]
                        continue
                    # Remove processed line from buffer
                    self.incoming = self.incoming[idx + 1 :]
                    # Decode raw bytes into string
                    decoded_line = self._decode_sensor_data(raw_line)

                    print(decoded_line)

                    # Extract distance value
                    return self._extract_distance_from_line(decoded_line)

    def _decode_sensor_data(self, raw_line) -> str | None:
        """
        Decode raw UART bytes into ASCII string.

        Args:
            raw_line: Raw byte string from UART

        Returns:
            str: Cleaned ASCII string

        Raises:
            Exception: If decoding fails
        """

        try:
            # Decode ASCII, ignoring invalid characters
            line: str = raw_line.decode("ascii", "ignore").strip("\r")

            if line:
                return line

            return None

        except Exception:
            raise Exception("No data read")

    def _extract_distance_from_line(self, processed_line) -> int | None:
        """
        Extract numeric distance value from processed sensor output.

        Expected format:
            "Range XXX"

        Args:
            processed_line: Decoded string line

        Returns:
            int: Distance value or None if invalid
        """
        if processed_line == "ON":
            return None
        if processed_line.startswith("Range "):
            try:
                return int(processed_line[6:])
            except Exception:
                raise Exception("Data coulnd't be parsed")

        return None

    def _handle_errors(self, e: Exception):
        self.continuous_fails += 1
        print(f"Err count {self.continuous_fails}")
        if self.continuous_fails == 5:
            self._set_sensor_normal_reading_mode()

        if self.continuous_fails >= 100 and self.continuous_fails % 100 == 0:
            # TODO: notify via bluethoot
            pass

    async def run_sensor_async(self):
        """
        Main loop:
        - Initializes sensor
        - Continuously reads data
        - Handles communication failures
        """
        self._set_sensor_normal_reading_mode()

        while True:
            try:
                data = self._read_sensor_data()
                if data is not None:
                    self.last_distance = data
                    self.continuous_fails = 0
            except Exception as e:
                self._handle_errors(e)

            await asyncio.sleep_ms(self.sensor_reading_wait_ms)
