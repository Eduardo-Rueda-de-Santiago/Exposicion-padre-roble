import os
import re
import threading
import time
import json
import serial
import serial.tools.list_ports

from services.database import db_service
from services.audio_player import audio_service

# Serial configuration
SERIAL_PORT = "/dev/cu.usbserial-0001"
BAUD_RATE = 115200

class SerialReaderService:
    def __init__(self):
        self._threads = []
        self._running = False
        self._default_threshold = 40.0 
        self._sensor_thresholds = {}
        self.reload_config()

    def reload_config(self):
        print("[SerialReader] Reloading configuration...")
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "sensor_audio_map.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                sensors = config.get("sensors", {})
                for sensor_id, data in sensors.items():
                    self._sensor_thresholds[sensor_id] = float(data.get("min_distance", self._default_threshold))
        except Exception as e:
            print(f"[SerialReader] Error loading config, using default thresholds: {e}")

    def parse_line(self, line: str):
        # Expected format: ESP_COLUMN_1|142.00
        match = re.search(r"(ESP_COLUMN_(\d+))\|(\d+\.?\d*)", line)
        if match:
            sensor_id = match.group(1)
            col_num = int(match.group(2))
            val = float(match.group(3))
            return sensor_id, col_num, val
        return None, None, None

    def _serial_reader_worker(self, port):
        try:
            print(f"Attempting to open serial port {port}...")
            ser = serial.Serial(port, BAUD_RATE, timeout=1)
            print(f"Connected to {port}!")
        except Exception as e:
            print(f"Failed to connect to {port}: {e}")
            return

        while self._running:
            try:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if line:
                    print(f"SERIAL_IN ({port}): '{line}'")
                    sensor_id, col_num, val = self.parse_line(line)
                    if sensor_id and val is not None and val != -1:
                        # Add to database
                        db_service.add_reading(sensor_id, val)
                        # Trigger audio if close
                        threshold = self._sensor_thresholds.get(sensor_id, self._default_threshold)
                        if val < threshold:
                            audio_service.trigger_sensor(sensor_id)
                    else:
                        if "[DEBUG]" not in line and "hello" not in line.lower():
                            pass
            except Exception as e:
                print(f"Error in serial reader on {port}: {e}")
                time.sleep(0.5)
        
        try:
            ser.close()
        except:
            pass

    def _manager_thread(self):
        available_ports = list(serial.tools.list_ports.comports())
        print("\n--- Available Serial Ports ---")
        for p in available_ports:
            print(f"Port: {p.device}, Description: {p.description}, HWID: {p.hwid}")
        print("------------------------------\n")

        ports_to_try = [SERIAL_PORT] + [p.device for p in available_ports]
        ports_to_try = list(dict.fromkeys(ports_to_try))

        if not ports_to_try:
            print("Error: No serial ports available. Serial reader disabled.")
            return

        for port in ports_to_try:
            t = threading.Thread(target=self._serial_reader_worker, args=(port,), daemon=True)
            t.start()
            self._threads.append(t)

        while self._running:
            time.sleep(1)

    def start(self):
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._manager_thread, daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=2.0)

serial_reader_service = SerialReaderService()
