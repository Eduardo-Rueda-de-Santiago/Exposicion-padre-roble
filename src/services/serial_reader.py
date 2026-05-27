import json
import os
import re
import threading
import time

import serial
import serial.tools.list_ports

# from services.audio_player import audio_service
from services.database import db_service

# Serial configuration
SERIAL_PORT = "COM16"
BAUD_RATE = 115200
RECONNECT_DELAY = 5.0  # seconds between reconnect attempts
OPEN_TIMEOUT = 3.0  # seconds before giving up on serial.Serial() open


class SerialReaderService:
    def __init__(self):
        self._thread = None
        self._running = False
        self._default_threshold = 40.0
        self._sensor_thresholds = {}
        self.reload_config()

    def reload_config(self):
        print("[SerialReader] Reloading configuration...")
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "sensor_audio_map.json"
        )
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                sensors = config.get("sensors", {})
                for sensor_id, data in sensors.items():
                    self._sensor_thresholds[sensor_id] = float(
                        data.get("min_distance", self._default_threshold)
                    )
        except Exception as e:
            print(f"[SerialReader] Error loading config, using default thresholds: {e}")

    def parse_line(self, line: str):
        # Expected format: ESP_COLUMN_1|142.00
        match = re.fullmatch(r"(ESP_COLUMN_(\d+))\|(-?\d+(?:\.\d+)?)", line)
        if match:
            sensor_id = match.group(1)
            col_num = int(match.group(2))
            val = float(match.group(3))
            return sensor_id, col_num, val
        return None, None, None

    def _open_serial(self, port: str) -> serial.Serial | None:
        """
        Open the serial port in a worker thread so that the call can never
        block the caller beyond OPEN_TIMEOUT seconds.
        Returns the open Serial object, or None on failure.
        """
        result = [None]
        error = [None]

        def _open():
            try:
                result[0] = serial.Serial(port, BAUD_RATE, timeout=1)
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_open, daemon=True)
        t.start()
        t.join(timeout=OPEN_TIMEOUT)

        if t.is_alive():
            # The open call is still hanging — abandon it.
            print(f"[SerialReader] Timed out opening {port} after {OPEN_TIMEOUT}s")
            return None

        if error[0]:
            print(f"[SerialReader] Failed to open {port}: {error[0]}")
            return None

        return result[0]

    def _log_available_ports(self):
        available = list(serial.tools.list_ports.comports())
        print("\n--- Available Serial Ports ---")
        for p in available:
            print(f"  {p.device}  |  {p.description}  |  {p.hwid}")
        print("------------------------------\n")

    def _reader_loop(self):
        """
        Single worker thread: tries to (re)connect to SERIAL_PORT and read
        lines indefinitely until self._running is False.
        """
        self._log_available_ports()

        while self._running:
            ser = self._open_serial(SERIAL_PORT)

            if ser is None:
                print(
                    f"[SerialReader] Could not open {SERIAL_PORT}. "
                    f"Retrying in {RECONNECT_DELAY}s..."
                )
                # Wait with short-circuit on stop()
                for _ in range(int(RECONNECT_DELAY / 0.2)):
                    if not self._running:
                        return
                    time.sleep(0.2)
                continue

            print(f"[SerialReader] Connected to {SERIAL_PORT}!")

            try:
                while self._running:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    print(f"SERIAL_IN: '{line}'")
                    sensor_id, _col, val = self.parse_line(line)

                    if sensor_id and val is not None and val != -1:
                        db_service.add_reading(sensor_id, val)
                        threshold = self._sensor_thresholds.get(
                            sensor_id, self._default_threshold
                        )
                        if val < threshold:
                            pass
                            # audio_service.trigger_sensor(sensor_id)

            except Exception as e:
                print(f"[SerialReader] Read error: {e}. Reconnecting...")
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

            if self._running:
                time.sleep(RECONNECT_DELAY)

        print("[SerialReader] Worker thread stopped.")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=OPEN_TIMEOUT + 2.0)
            self._thread = None


serial_reader_service = SerialReaderService()
