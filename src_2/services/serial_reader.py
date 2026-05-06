import os
import re
import threading
import time
import serial
import serial.tools.list_ports

from services.database import db_service
from services.audio_player import audio_service

# Serial configuration
SERIAL_PORT = "/dev/cu.usbserial-0001"
BAUD_RATE = 115200

class SerialReaderService:
    def __init__(self):
        self._thread = None
        self._running = False
        self._audio_threshold = 40.0 # Example threshold to trigger audio

    def parse_line(self, line: str):
        # Expected format: ESP_COLUMN_1|142.00
        match = re.search(r"(ESP_COLUMN_(\d+))\|(\d+\.?\d*)", line)
        if match:
            sensor_id = match.group(1)
            col_num = int(match.group(2))
            val = float(match.group(3))
            return sensor_id, col_num, val
        return None, None, None

    def _serial_reader_thread(self):
        available_ports = list(serial.tools.list_ports.comports())
        print("\n--- Available Serial Ports ---")
        for p in available_ports:
            print(f"Port: {p.device}, Description: {p.description}, HWID: {p.hwid}")
        print("------------------------------\n")

        ports_to_try = [SERIAL_PORT] + [p.device for p in available_ports]
        ports_to_try = list(dict.fromkeys(ports_to_try))

        ser = None
        for port in ports_to_try:
            try:
                print(f"Attempting to open serial port {port}...")
                ser = serial.Serial(port, BAUD_RATE, timeout=1)
                print(f"Connected to {port}!")
                break
            except Exception as e:
                print(f"Failed to connect to {port}: {e}")

        if not ser:
            print("Error: Could not open any serial port. Serial reader disabled.")
            return

        while self._running:
            try:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if line:
                    print(f"SERIAL_IN: '{line}'")
                    sensor_id, col_num, val = self.parse_line(line)
                    if sensor_id and val is not None and val != -1:
                        # Add to database
                        db_service.add_reading(sensor_id, val)
                        
                        # Trigger audio if close
                        if val < self._audio_threshold:
                            audio_service.trigger_column(col_num)
                    else:
                        if "[DEBUG]" not in line and "hello" not in line.lower():
                            pass
            except Exception as e:
                print(f"Error in serial reader: {e}")
                time.sleep(0.5)
        
        if ser:
            ser.close()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serial_reader_thread, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

serial_reader_service = SerialReaderService()
