"""
BLE Sender - Peripheral Role  (ESP_COLUMN_1)
=============================================
Advertises as ESP_COLUMN_1 and waits for the central receiver to connect.
Once connected, reads an ultrasonic sensor every 500 ms and sends the
distance (float, 2 decimal places) as a BLE notification.

LED behaviour:
  - Not connected : fast blink every 0.05 s
  - Connected     : slow blink every 1.0 s

Sensor:
  - HC-SR04 (or compatible) ultrasonic sensor
  - TRIG_PIN = 12
  - ECHO_PIN = 13

UUIDs — must match the central (ble_receiver.py):
  SERVICE_UUID        = 0x1234
  CHARACTERISTIC_UUID = 0x5678
"""

import asyncio
import bluetooth
from micropython import const
from machine import Pin, time_pulse_us

# ---------------------------------------------------------------------------
# Identity — edit COLUMN_NUMBER to change which column this board is
# ---------------------------------------------------------------------------
COLUMN_NUMBER = 1
DEVICE_NAME   = f"ESP_COLUMN_{COLUMN_NUMBER}"

# ---------------------------------------------------------------------------
# BLE UUIDs  (must match central)
# ---------------------------------------------------------------------------
SERVICE_UUID        = bluetooth.UUID(0x1234)
CHARACTERISTIC_UUID = bluetooth.UUID(0x5678)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MEASURE_INTERVAL_MS  = const(500)   # Distance measurement period
BLINK_DISCONNECTED   = 0.05         # LED period when advertising (s)
BLINK_CONNECTED      = 1.0          # LED period when connected (s)

# Ultrasonic sensor pins
TRIG_PIN = const(12)
ECHO_PIN  = const(13)

# Speed of sound at ~20 C in cm/us
SOUND_CM_PER_US = 0.0343

# Valid range for HC-SR04 (cm)
SENSOR_MIN_CM = 2.0
SENSOR_MAX_CM = 400.0

# Echo timeout: 400 cm * 2 / 0.0343 cm/us ~ 23 320 us, rounded up
ECHO_TIMEOUT_US = const(25_000)

# ---------------------------------------------------------------------------
# LED helpers
# ---------------------------------------------------------------------------
try:
    _led = Pin(2, Pin.OUT)
    def led_on():  _led.value(1)
    def led_off(): _led.value(0)
except Exception:
    def led_on():  pass
    def led_off(): pass

# ---------------------------------------------------------------------------
# Ultrasonic sensor
# ---------------------------------------------------------------------------
_trig = Pin(TRIG_PIN, Pin.OUT)
_echo = Pin(ECHO_PIN, Pin.IN)

def read_distance_cm():
    """
    Trigger an HC-SR04 pulse and return distance in cm (float, 2 dp).
    Returns None on timeout or out-of-range reading (silently skipped).
    """
    _trig.value(0)
    _trig.value(1)
    for _ in range(10):   # ~10 us busy pulse
        pass
    _trig.value(0)

    duration_us = time_pulse_us(_echo, 1, ECHO_TIMEOUT_US)

    if duration_us < 0:
        return None     # Timeout

    distance = (duration_us * SOUND_CM_PER_US) / 2.0

    if distance < SENSOR_MIN_CM or distance > SENSOR_MAX_CM:
        return None     # Out of valid sensor range

    return round(distance, 2)

# ---------------------------------------------------------------------------
# BLE Peripheral
# ---------------------------------------------------------------------------
# const() must be at module level in MicroPython — class-level const() is not
# accessible via self and raises AttributeError at runtime
_FLAG_READ   = const(0x0002)
_FLAG_NOTIFY = const(0x0010)

class BLEPeripheral:
    def __init__(self, name: str):
        self._name        = name
        self._connected   = False
        self._conn_handle = None

        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        # Register GATT service + characteristic
        ((self._char_handle,),) = self._ble.gatts_register_services((
            (SERVICE_UUID, (
                (CHARACTERISTIC_UUID, _FLAG_READ | _FLAG_NOTIFY),
            )),
        ))

        # asyncio Events for connection state changes
        self.connected_event    = asyncio.Event()
        self.disconnected_event = asyncio.Event()

    # ------------------------------------------------------------------
    # IRQ
    # ------------------------------------------------------------------
    def _irq(self, event, data):

        if event == 1:   # Central connected
            conn_handle, addr_type, addr = data
            self._conn_handle = conn_handle
            self._connected   = True
            self.connected_event.set()
            self.disconnected_event.clear()

        elif event == 2:  # Central disconnected
            self._conn_handle = None
            self._connected   = False
            self.disconnected_event.set()
            self.connected_event.clear()
            self._advertise()  # Resume advertising for reconnection

    # ------------------------------------------------------------------
    # Advertising
    # ------------------------------------------------------------------
    def _advertise(self):
        name_bytes = self._name.encode("utf-8")
        flags  = b'\x02\x01\x06'                              # LE General Discoverable
        name_ad = bytes([len(name_bytes) + 1, 0x09]) + name_bytes  # Complete Local Name
        self._ble.gap_advertise(100_000, adv_data=flags + name_ad)

    def start(self):
        self._advertise()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    def send(self, value: float):
        if not self._connected or self._conn_handle is None:
            return
        payload = "{:.2f}".format(value).encode("utf-8")
        self._ble.gatts_notify(self._conn_handle, self._char_handle, payload)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
async def led_task(peripheral: BLEPeripheral):
    while True:
        period = BLINK_CONNECTED if peripheral.connected else BLINK_DISCONNECTED
        led_on()
        await asyncio.sleep(period / 2)
        led_off()
        await asyncio.sleep(period / 2)


async def sensor_task(peripheral: BLEPeripheral):
    """
    Waits until connected, then measures and sends distance every 500 ms.
    Pauses automatically on disconnect and resumes on reconnection.
    """
    while True:
        if not peripheral.connected:
            print("[{}] Waiting for central...".format(DEVICE_NAME))
            await peripheral.connected_event.wait()
            print("[{}] Connected - starting measurements.".format(DEVICE_NAME))

        distance = read_distance_cm()

        if distance is None:
            distance = -1
        peripheral.send(distance)

        await asyncio.sleep_ms(MEASURE_INTERVAL_MS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    print("[BOOT] {} starting...".format(DEVICE_NAME))
    print("[BOOT] SERVICE_UUID        = 0x1234")
    print("[BOOT] CHARACTERISTIC_UUID = 0x5678")
    print("[BOOT] Advertising as '{}'".format(DEVICE_NAME))

    led_on()

    peripheral = BLEPeripheral(DEVICE_NAME)
    peripheral.start()

    asyncio.create_task(led_task(peripheral))
    asyncio.create_task(sensor_task(peripheral))

    while True:
        await asyncio.sleep(60)

asyncio.run(main())  