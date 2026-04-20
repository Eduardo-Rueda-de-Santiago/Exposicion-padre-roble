import serial
import serial.tools.list_ports
import threading
import time
import re
import os
import simpleaudio as sa
from database import add_reading

# Serial configuration
SERIAL_PORT = '/dev/cu.usbserial-0001'
BAUD_RATE = 115200

# Audio state
audio_playing = False

def play_audio(filename):
    global audio_playing
    try:
        # Check if file exists before playing
        filepath = os.path.join(os.path.dirname(__file__), 'sounds', filename)
        if not os.path.exists(filepath):
            print(f"Warning: Audio file {filepath} not found.")
            return

        wave_obj = sa.WaveObject.from_wave_file(filepath)
        play_obj = wave_obj.play()
        audio_playing = True
        
        # Wait for audio to finish playing in a separate thread to not block serial reading
        def wait_and_reset():
            global audio_playing
            play_obj.wait_done()
            audio_playing = False
            
        threading.Thread(target=wait_and_reset, daemon=True).start()

    except Exception as e:
        print(f"Error playing audio: {e}")
        audio_playing = False

def parse_line(line):
    match = re.search(r'[-|](\d+\.?\d*)', line)
    if match:
        return float(match.group(1))
    return None

def serial_reader_thread():
    global audio_playing
    
    # List all available ports to help debugging
    available_ports = list(serial.tools.list_ports.comports())
    print("\n--- Available Serial Ports ---")
    for p in available_ports:
        print(f"Port: {p.device}, Description: {p.description}, HWID: {p.hwid}")
    print("------------------------------\n")

    # Try different common port names and also auto-discovered ones
    ports_to_try = [SERIAL_PORT] + [p.device for p in available_ports]
    # Remove duplicates while preserving order
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

    while True:
        try:
            # Reverting to readline() as it was proven to work for the user
            line = ser.readline().decode('utf-8', errors='replace').strip()
            
            if line:
                # Log every line received
                print(f"SERIAL_IN: '{line}'")
                
                val = parse_line(line)
                if val is not None and val != -1:
                    print(f"    >>> VALID DATA: {val}")
                    add_reading('ESP_COLUMN_1', val)
                    
                    if val < 20 and not audio_playing:
                        play_audio('lyre.wav')
                    elif 20 <= val < 40 and not audio_playing:
                        play_audio('guitar.wav')
                else:
                    # If it's not our specific format, just log it quietly if it's debug
                    if "[DEBUG]" not in line and "hello" not in line.lower():
                        print(f"    (No data found in line)")
                            
        except Exception as e:
            print(f"Error in serial reader: {e}")
            time.sleep(0.5)

def start_serial_reader():
    thread = threading.Thread(target=serial_reader_thread, daemon=True)
    thread.start()
    return thread
