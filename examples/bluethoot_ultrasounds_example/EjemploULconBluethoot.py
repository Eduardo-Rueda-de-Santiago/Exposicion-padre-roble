import bluetooth
import time
import uasyncio as asyncio
from machine import Pin, time_pulse_us

# ─── Pin config ───────────────────────────────────────────────
TRIG_PIN   = 12
ECHO_PIN   = 13
LED_PIN    = 2

DETECT_CM  = 10       # Detection threshold in cm
POLL_MS    = 100      # Sensor poll interval (ms) — 10Hz is plenty for HC-SR04
COOLDOWN_S = 3        # Seconds before re-sending "person nearby" alert

# ─── BLE UART UUIDs (Nordic UART Service) ─────────────────────
UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
UART_RX_UUID      = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
UART_TX_UUID      = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")

UART_RX      = (UART_RX_UUID, bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
UART_TX      = (UART_TX_UUID, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY)
UART_SERVICE = (UART_SERVICE_UUID, (UART_TX, UART_RX))

_IRQ_CENTRAL_CONNECT    = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE        = 3

# ─── Hardware ─────────────────────────────────────────────────
led  = Pin(LED_PIN,  Pin.OUT)
trig = Pin(TRIG_PIN, Pin.OUT)
echo = Pin(ECHO_PIN, Pin.IN)
led.value(0)
trig.value(0)

# ─── Shared state ─────────────────────────────────────────────
conn_handle    = None
tx_handle      = None
rx_handle      = None
last_alert_ts  = 0        # timestamp of last "person nearby" send
person_present = False    # tracks current detection state

# ─── BLE setup ────────────────────────────────────────────────
ble = bluetooth.BLE()
ble.active(True)

((tx_handle, rx_handle),) = ble.gatts_register_services((UART_SERVICE,))

def ble_send(text):
    """Send a string to the connected phone via NOTIFY."""
    if conn_handle is None:
        return
    try:
        data = (text + "\n").encode()
        ble.gatts_write(tx_handle, data)
        ble.gatts_notify(conn_handle, tx_handle)
        print("[TX]", text)
    except Exception as e:
        print("[TX ERROR]", e)

def _adv_payload(name):
    payload = bytearray()
    payload += bytearray([2, 0x01, 0x06])          # Flags
    n = name.encode()
    payload += bytearray([len(n) + 1, 0x09]) + n   # Complete name
    return payload

def advertise():
    ble.gap_advertise(100_000, adv_data=_adv_payload("ESP32_SONAR"))
    print("[BLE] Advertising as ESP32_SONAR...")

def on_ble_irq(event, data):
    global conn_handle
    if event == _IRQ_CENTRAL_CONNECT:
        conn_handle, _, _ = data
        print(f"[BLE] Connected — handle {conn_handle}")
        time.sleep_ms(300)
        ble_send("ESP32 Ultrasonic ready!")
        ble_send(f"Alerting when object < {DETECT_CM}cm")

    elif event == _IRQ_CENTRAL_DISCONNECT:
        conn_handle = None
        led.value(0)
        print("[BLE] Disconnected — restarting advertising")
        advertise()

    elif event == _IRQ_GATTS_WRITE:
        _, attr_handle = data
        if attr_handle == rx_handle:
            raw = ble.gatts_read(rx_handle)
            try:
                received = raw.decode().strip().lower()
            except Exception:
                return

            # Normalise hex digit input from LightBlue
            cmd = received
            if len(raw) == 1 and 0x30 <= raw[0] <= 0x39:
                cmd = str(raw[0] - 0x30)

            print(f"[RX] '{cmd}'")

            if cmd in ("0", "off"):
                led.value(0)
                ble_send("0: LED off")
            elif cmd in ("1", "on"):
                led.value(1)
                ble_send("1: LED on")
            elif cmd in ("2", "ping"):
                ble_send("2: pong")
            elif cmd in ("3", "distance"):
                d = measure_distance_cm()
                if d is None:
                    ble_send("3: Sensor timeout")
                else:
                    ble_send(f"3: Distance = {d:.1f} cm")
            else:
                ble_send(f"Unknown: '{cmd}'")
                ble_send("0=led off  1=led on  2=ping  3=distance")

ble.irq(on_ble_irq)

# ─── HC-SR04 measurement ──────────────────────────────────────
def measure_distance_cm():
    """
    Trigger the HC-SR04 and return distance in cm.
    Returns None on timeout (no echo / out of range).
    Uses time_pulse_us for µs-accurate echo timing without
    blocking the async loop for more than ~30ms worst case.
    """
    # Send 10µs trigger pulse
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    # Measure echo pulse width (timeout = 30ms → ~5m max range)
    pulse_us = time_pulse_us(echo, 1, 30_000)

    if pulse_us < 0:
        return None  # Timeout or no object detected

    # Speed of sound: 340 m/s → 0.034 cm/µs, round trip ÷ 2
    return (pulse_us * 0.034) / 2

# ─── Async tasks ──────────────────────────────────────────────

async def sensor_task():
    """
    Core 0 cooperative task: polls HC-SR04 at POLL_MS intervals.
    Drives LED and BLE alerts based on proximity.
    Runs on the MicroPython event loop alongside BLE.
    """
    global person_present, last_alert_ts

    print("[SENSOR] Starting ultrasonic polling loop")
    while True:
        distance = measure_distance_cm()

        if distance is None:
            # Out of range or sensor error — treat as clear
            if person_present:
                person_present = False
                led.value(0)
                ble_send("Area clear")
                print("[SENSOR] Area clear")

        elif distance < DETECT_CM:
            led.value(1)
            print(f"[SENSOR] Object at {distance:.1f} cm — ALERT")

            if not person_present:
                # Rising edge: just entered range
                person_present = True
                ble_send(f"Person nearby ({distance:.1f} cm)")
                last_alert_ts = time.time()

            else:
                # Already detected — re-alert after cooldown to avoid spam
                now = time.time()
                if (now - last_alert_ts) >= COOLDOWN_S:
                    ble_send(f"Person nearby ({distance:.1f} cm)")
                    last_alert_ts = now

        else:
            # Object present but beyond threshold
            if person_present:
                person_present = False
                led.value(0)
                ble_send(f"Area clear ({distance:.1f} cm)")
                print(f"[SENSOR] Cleared — {distance:.1f} cm")

        # Yield control back to the event loop between readings
        await asyncio.sleep_ms(POLL_MS)


async def heartbeat_task():
    """
    Optional: blinks LED slowly when disconnected so you can see
    the board is alive without a phone connected.
    """
    print("[HEARTBEAT] Starting")
    while True:
        if conn_handle is None:
            led.value(1)
            await asyncio.sleep_ms(80)
            led.value(0)
            await asyncio.sleep_ms(2920)   # slow blink every 3s
        else:
            await asyncio.sleep_ms(500)


async def main():
    print("[BOOT] ESP32 BLE Ultrasonic starting...")
    advertise()

    # Schedule both tasks — they interleave cooperatively on Core 0.
    # BLE IRQs fire between awaits so nothing is starved.
    asyncio.create_task(heartbeat_task())
    asyncio.create_task(sensor_task())

    # Keep the event loop alive
    while True:
        await asyncio.sleep_ms(1000)

# ─── Entry point ──────────────────────────────────────────────
time.sleep_ms(500)   # Settle after Thonny reset
asyncio.run(main())