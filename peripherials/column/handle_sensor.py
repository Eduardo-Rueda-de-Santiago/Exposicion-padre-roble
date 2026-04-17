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
from common_data_storage import DataStorage

# UART communication settings
BAUD_RATE = 115200
DEFAULT_UART_ID = 2

# Default GPIO pin mapping (ESP32 UART2)
DEFAULT_UART_RX = 16  # Sensor TX → ESP32 GPIO16
DEFAULT_UART_TX = 17  # Sensor RX → ESP32 GPIO17

# Sensor initialization command (hex string).
# Switches the HMMD sensor into continuous "normal reading mode"
# as defined in the official communication protocol documentation.
INIT_HEX = "FDFCFBFA0800120000006400000004030201"

# How many consecutive parse failures trigger a sensor re-init
REINIT_FAIL_THRESHOLD = 5

# How many consecutive failures mark the sensor as unhealthy
FAILING_STATE_THRESHOLD = 100


class MotionSensor:
    """
    Interface for the Waveshare HMMD mmWave motion sensor.

    Responsibilities:
    - Initialize UART communication.
    - Send configuration commands to the sensor.
    - Read and parse incoming sensor data.
    - Write distance measurements to a shared DataStorage instance
      so other tasks (LED controller, etc.) can consume them.
    """

    def __init__(
        self,
        common_data_storage: DataStorage,
        uart_id: int = DEFAULT_UART_ID,
        uart_rx_pin: int = DEFAULT_UART_RX,
        uart_tx_pin: int = DEFAULT_UART_TX,
        sensor_reading_wait_ms: int = 10,
    ) -> None:
        """
        Initialize UART communication and internal state.

        Args:
            common_data_storage: Shared storage written to after each
                                  successful reading and read by other tasks.
            uart_id: UART interface ID (ESP32 typically uses UART2).
            uart_rx_pin: GPIO pin for UART RX (connected to sensor TX).
            uart_tx_pin: GPIO pin for UART TX (connected to sensor RX).
            sensor_reading_wait_ms: Delay between polling cycles (ms).
                                     Yielding here is what lets the LED
                                     coroutine run on the cooperative scheduler.
        """
        self.uart = machine.UART(
            uart_id,
            baudrate=BAUD_RATE,
            rx=uart_rx_pin,
            tx=uart_tx_pin,
            bits=8,
            parity=None,
            stop=1,
        )

        self.common_data_storage = common_data_storage
        self.sensor_reading_wait_ms = sensor_reading_wait_ms

        # Buffer for accumulating incoming UART bytes between poll cycles
        self.incoming = bytearray()

        # Counter for consecutive read/parse failures
        self.continuous_fails = 0

    # ───────────────────────── UART helpers ─────────────────────────

    def _send_hex_data(self, hex_string: str) -> None:
        """
        Convert a hexadecimal string to raw bytes and send over UART.

        Args:
            hex_string: Hex-encoded bytes, e.g. "FDFCFBFA...".
        """
        self.uart.write(bytes.fromhex(hex_string))

    def _set_sensor_normal_reading_mode(self) -> None:
        """Send the initialization command that enables continuous measurement."""
        self._send_hex_data(INIT_HEX)

    # ───────────────────────── Data parsing ─────────────────────────

    def _read_sensor_data(self) -> int | None:
        """
        Drain the UART buffer, process the first complete line found,
        and return a distance value if one can be parsed.

        Returns:
            Distance in cm, or None if no complete/valid line is available yet.
        """
        n = self.uart.any()
        if not n:
            return None

        chunk = self.uart.read(n)
        if not chunk:
            return None

        self.incoming += chunk

        # Process the first complete newline-terminated line in the buffer.
        # Remaining bytes stay in self.incoming for the next poll cycle.
        if b"\n" not in self.incoming:
            return None

        idx = self.incoming.index(b"\n")
        raw_line = self.incoming[:idx]
        self.incoming = self.incoming[idx + 1 :]

        if not raw_line:
            return None

        decoded_line = self._decode_sensor_data(raw_line)
        if decoded_line is None:
            return None

        print(decoded_line)
        return self._extract_distance_from_line(decoded_line)

    def _decode_sensor_data(self, raw_line: bytes) -> str | None:
        """
        Decode raw UART bytes into a clean ASCII string.

        Args:
            raw_line: Raw bytes from UART.

        Returns:
            Stripped ASCII string, or None if the result is empty.

        Raises:
            Exception: If decoding raises an unexpected error.
        """
        try:
            line = raw_line.decode("ascii", "ignore").strip("\r")
            return line if line else None
        except Exception:
            raise Exception("Failed to decode sensor data")

    def _extract_distance_from_line(self, processed_line: str) -> int | None:
        """
        Extract the numeric distance value from a decoded sensor line.

        Expected format: "Range XXX"  (e.g. "Range 142")
        "ON" lines are silently ignored (sensor presence heartbeat).

        Args:
            processed_line: Decoded sensor output string.

        Returns:
            Distance as int, or None if the line carries no distance.

        Raises:
            Exception: If a "Range" line cannot be parsed as an integer.
        """
        if processed_line == "ON":
            return None

        if processed_line.startswith("Range "):
            try:
                return int(processed_line[6:])
            except Exception:
                raise Exception("Distance value could not be parsed")

        return None

    # ───────────────────────── Error handling ─────────────────────────

    def _handle_errors(self, e: Exception) -> None:
        """
        Track consecutive failures and take corrective action.

        - After REINIT_FAIL_THRESHOLD failures: re-send the init command.
        - After FAILING_STATE_THRESHOLD failures (and every 100 thereafter):
          flag the sensor as unhealthy in shared storage.
        """
        self.continuous_fails += 1
        print(f"Sensor error #{self.continuous_fails}: {e}")

        if self.continuous_fails == REINIT_FAIL_THRESHOLD:
            print("Re-initializing sensor...")
            self._set_sensor_normal_reading_mode()

        if (
            self.continuous_fails >= FAILING_STATE_THRESHOLD
            and self.continuous_fails % 100 == 0
        ):
            self.common_data_storage.set_sensor_failing_state(True)

    # ───────────────────────── Async entry point ─────────────────────────

    async def run_sensor_async(self) -> None:
        """
        Async task entry point.

        Initializes the sensor, then loops forever:
        - Reads available data from UART.
        - On success: writes the distance to shared storage and clears
          the failure counter.
        - On failure: delegates to _handle_errors.
        - Yields to the scheduler via asyncio.sleep_ms so other tasks
          (e.g. the LED coroutine) get CPU time.
        """
        self._set_sensor_normal_reading_mode()

        while True:
            try:
                distance = self._read_sensor_data()
                if distance is not None:
                    self.common_data_storage.update_distance(distance)
                    self.common_data_storage.set_sensor_failing_state(False)
                    self.continuous_fails = 0
            except Exception as e:
                self._handle_errors(e)

            # ← This await is what gives the LED task (and any other
            #   coroutines) a chance to run between sensor polls.
            await asyncio.sleep_ms(self.sensor_reading_wait_ms)
