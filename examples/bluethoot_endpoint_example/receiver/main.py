"""
BLE Receiver - Central Role (uasyncio implementation)
======================================================
Scans for and connects to devices named ESP_COLUMN_<N> or ADMIN.
Forwards all received messages to serial in the format:
    <DeviceID>-<received_message>

Task model:
  - led_task        : Blinks LED reflecting global connection state
  - scan_task       : Periodic BLE scan + connection attempts (every 10 s)
  - rx_task         : One per connected device, forwards notifications to serial
  - error_task      : Monitors failed devices, reports + retries every 60 s

UUIDs (match these on every ESP_COLUMN transmitter):
  SERVICE_UUID        = 0x1234
  CHARACTERISTIC_UUID = 0x5678
"""

import asyncio

import bluetooth
from micropython import const

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_UUID = bluetooth.UUID(0x1234)
CHARACTERISTIC_UUID = bluetooth.UUID(0x5678)

SCAN_INTERVAL_S = const(10)  # Re-scan for new devices every 10 s
RECONNECT_INTERVAL_S = const(60)  # Wait between error reports / retries
MAX_RECONNECT_FAST = const(5)  # Failures before switching to 1/min retry
CONNECT_TIMEOUT_S = const(5)  # Max wait for a connection to establish
SCAN_DURATION_MS = const(3_000)  # BLE scan window

BLINK_DISCONNECTED = 0.05  # LED blink period when searching (s)
BLINK_CONNECTED = 1.0  # LED blink period when >=1 device up (s)

# ---------------------------------------------------------------------------
# LED helpers
# ---------------------------------------------------------------------------
try:
    from machine import Pin

    _led = Pin(2, Pin.OUT)

    def led_on():
        _led.value(1)

    def led_off():
        _led.value(0)
except Exception:

    def led_on():
        pass

    def led_off():
        pass


# ---------------------------------------------------------------------------
# Serial output
# ---------------------------------------------------------------------------
def serial_print(msg: str):
    print(msg)


# ---------------------------------------------------------------------------
# Device name validation
# ---------------------------------------------------------------------------
def is_allowed_name(name: str) -> bool:
    """Accept ESP_COLUMN_<N> (any integer suffix) or ADMIN."""
    if name == "ADMIN":
        return True
    if name.startswith("ESP_COLUMN_"):
        suffix = name[len("ESP_COLUMN_") :]
        return suffix.isdigit()
    return False


# ---------------------------------------------------------------------------
# Device state
# ---------------------------------------------------------------------------
class DeviceInfo:
    def __init__(self, name: str, addr: bytes, addr_type: int):
        self.name = name
        self.addr = addr
        self.addr_type = addr_type
        self.connected = False
        self.conn_handle = None
        self.fail_count = 0
        # asyncio.Event signals rx_task that a notification has arrived
        self.rx_event = asyncio.Event()
        # Notification buffer — only touched inside the event loop (no lock needed)
        self.rx_buffer = []
        self.value_handle = None


# Global device registry  { name: DeviceInfo }
devices: dict = {}


# ---------------------------------------------------------------------------
# BLE Central
# ---------------------------------------------------------------------------
class BLECentral:
    def __init__(self):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        # Scan results — filled by IRQ, consumed by scan_task
        self._scan_results: dict = {}  # addr_hex -> {name, addr, addr_type}
        self._scan_done = asyncio.Event()

        # Pending connections  addr_hex -> name
        self._pending: dict = {}

    # ------------------------------------------------------------------
    # IRQ handler — runs in IRQ context: must be fast, no allocations
    # ------------------------------------------------------------------
    def _irq(self, event, data):

        # --- Scan result ---
        if event == 5:
            addr_type, addr, adv_type, rssi, adv_data = data
            name = self._decode_name(bytes(adv_data))
            if name and is_allowed_name(name):
                addr_hex = bytes(addr).hex()
                self._scan_results[addr_hex] = {
                    "name": name,
                    "addr": bytes(addr),
                    "addr_type": addr_type,
                }

        # --- Scan complete ---
        elif event == 6:
            self._scan_done.set()

        # --- Peripheral connected ---
        elif event == 7:
            conn_handle, addr_type, addr = data
            addr_hex = bytes(addr).hex()
            name = self._pending.pop(addr_hex, None)
            if name and name in devices:
                dev = devices[name]
                dev.connected = True
                dev.conn_handle = conn_handle
                dev.fail_count = 0
                self._ble.gattc_discover_services(conn_handle)

        # --- Peripheral disconnected ---
        elif event == 8:
            conn_handle, addr_type, addr = data
            for dev in devices.values():
                if dev.conn_handle == conn_handle:
                    dev.connected = False
                    dev.conn_handle = None
                    break

        # --- Service result ---
        elif event == 9:
            conn_handle, start_handle, end_handle, uuid = data
            if bluetooth.UUID(uuid) == SERVICE_UUID:
                self._ble.gattc_discover_characteristics(
                    conn_handle, start_handle, end_handle
                )

        # --- Characteristic result ---
        # elif event == 11:
        #     conn_handle, def_handle, value_handle, properties, uuid = data
        #     if bluetooth.UUID(uuid) == CHARACTERISTIC_UUID:
        #         # Write 0x0001 to CCCD (value_handle + 1) to enable notifications
        #         self._ble.gattc_write(
        #             conn_handle, value_handle + 1, b'\x01\x00', 1
        #         )
        elif event == 11:
            conn_handle, def_handle, value_handle, properties, uuid = data

            if bluetooth.UUID(uuid) == CHARACTERISTIC_UUID:
                for dev in devices.values():
                    if dev.conn_handle == conn_handle:
                        dev.value_handle = value_handle
                        break

                self._ble.gattc_write(conn_handle, value_handle + 1, b"\x01\x00", 1)

        # --- Notification received ---
        elif event == 18:
            # conn_handle, value_handle, notify_data = data
            # payload = bytes(notify_data)
            # for dev in devices.values():
            # if dev.conn_handle == conn_handle:
            # dev.rx_buffer.append(payload)
            # dev.rx_event.set()
            # break
            print("[DEBUG] Notification IRQ fired")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_name(adv_data: bytes):
        """Extract Complete/Shortened Local Name from raw advertisement payload."""
        i = 0
        while i < len(adv_data):
            length = adv_data[i]
            if length == 0:
                break
            type_ = adv_data[i + 1]
            if type_ in (0x08, 0x09):  # Shortened / Complete Local Name
                try:
                    return adv_data[i + 2 : i + 1 + length].decode("utf-8")
                except Exception:
                    return None
            i += 1 + length
        return None

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------
    async def scan(self) -> dict:
        """Scan for SCAN_DURATION_MS ms; return dict of allowed devices found."""
        self._scan_results.clear()
        self._scan_done.clear()
        self._ble.gap_scan(SCAN_DURATION_MS, 30_000, 30_000)
        try:
            await asyncio.wait_for(self._scan_done.wait(), SCAN_DURATION_MS / 1000 + 1)
        except asyncio.TimeoutError:
            self._ble.gap_scan(None)  # Force-stop scan
        return dict(self._scan_results)

    async def connect(self, dev: DeviceInfo) -> bool:
        """
        Initiate a BLE connection to dev.
        Returns True if connected within CONNECT_TIMEOUT_S seconds.
        """
        addr_hex = dev.addr.hex()
        self._pending[addr_hex] = dev.name
        self._ble.gap_connect(dev.addr_type, dev.addr)

        for _ in range(CONNECT_TIMEOUT_S * 10):  # Poll every 100 ms
            await asyncio.sleep_ms(100)
            if dev.connected:
                return True

        self._pending.pop(addr_hex, None)  # Timed out — clean up
        return False


# Singleton BLE central
central = BLECentral()


# ---------------------------------------------------------------------------
# Task: LED blinker
# ---------------------------------------------------------------------------
async def led_task():
    while True:
        any_connected = any(dev.connected for dev in devices.values())
        period = BLINK_CONNECTED if any_connected else BLINK_DISCONNECTED
        led_on()
        await asyncio.sleep(period / 2)
        led_off()
        await asyncio.sleep(period / 2)


# ---------------------------------------------------------------------------
# Task: per-device RX
# ---------------------------------------------------------------------------
async def rx_task(dev: DeviceInfo):
    """
    Waits for BLE notifications from a single device and writes them to serial.
    Exits cleanly on disconnect so scan_task / error_task can restart it.
    """
    serial_print(f"[INFO] rx_task started for {dev.name}")

    while dev.connected:
        try:
            await asyncio.wait_for(dev.rx_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue  # Loop back to re-check dev.connected

        dev.rx_event.clear()

        while dev.rx_buffer:
            payload = dev.rx_buffer.pop(0)
            try:
                message = payload.decode("utf-8").strip()
            except Exception:
                message = payload.hex()
            serial_print(f"{dev.name}-{message}")

    serial_print(f"[INFO] rx_task exiting for {dev.name} (disconnected)")


# ---------------------------------------------------------------------------
# Task: scan + connection manager
# ---------------------------------------------------------------------------
async def scan_task():
    """
    Every SCAN_INTERVAL_S seconds: scan for allowed devices not yet connected
    and attempt to connect. Spawns a fresh rx_task on each successful connection.
    """
    # Names with a currently live rx_task
    rx_active: set = set()

    while True:
        serial_print("[SCAN] Scanning for devices...")
        found = await central.scan()

        for addr_hex, info in found.items():
            name = info["name"]

            # Register new device
            if name not in devices:
                devices[name] = DeviceInfo(name, info["addr"], info["addr_type"])
                serial_print(f"[SCAN] Discovered: {name}")

            dev = devices[name]

            if dev.connected:
                # Ensure rx_task is alive (e.g. first scan after reconnect)
                if name not in rx_active:
                    asyncio.create_task(rx_task(dev))
                    rx_active.add(name)
                continue

            # Devices past the fast-retry threshold are handled by error_task
            if dev.fail_count >= MAX_RECONNECT_FAST:
                continue

            serial_print(f"[SCAN] Connecting to {name}...")
            success = await central.connect(dev)

            if success:
                serial_print(f"[INFO] Connected to {name}")
                asyncio.create_task(rx_task(dev))
                rx_active.add(name)
            else:
                dev.fail_count += 1
                serial_print(
                    f"[WARN] Failed to connect to {name} (attempt {dev.fail_count})"
                )

        # Prune names whose rx_task has exited (device disconnected)
        rx_active = {n for n in rx_active if n in devices and devices[n].connected}

        await asyncio.sleep(SCAN_INTERVAL_S)


# ---------------------------------------------------------------------------
# Task: error reporter + slow reconnect
# ---------------------------------------------------------------------------
async def error_task():
    """
    Every RECONNECT_INTERVAL_S seconds: for every disconnected device that has
    reached MAX_RECONNECT_FAST failures, print an error and attempt one reconnect.
    Repeats indefinitely to support manual recovery.
    """
    while True:
        await asyncio.sleep(RECONNECT_INTERVAL_S)

        for dev in list(devices.values()):
            if dev.connected or dev.fail_count < MAX_RECONNECT_FAST:
                continue

            serial_print(
                f"[ERROR] {dev.name} is unreachable. "
                f"Total failed attempts: {dev.fail_count}. "
                f"Manual intervention may be required."
            )
            serial_print(f"[RETRY] Attempting reconnect to {dev.name}...")

            success = await central.connect(dev)

            if success:
                dev.fail_count = 0
                serial_print(f"[INFO] Reconnected to {dev.name} successfully.")
                asyncio.create_task(rx_task(dev))
            else:
                dev.fail_count += 1
                serial_print(
                    f"[ERROR] Reconnect failed for {dev.name}. "
                    f"Total failed attempts: {dev.fail_count}."
                )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    serial_print("[BOOT] BLE Receiver starting...")
    serial_print("[BOOT] SERVICE_UUID        = 0x1234")
    serial_print("[BOOT] CHARACTERISTIC_UUID = 0x5678")

    asyncio.create_task(led_task())
    asyncio.create_task(scan_task())
    asyncio.create_task(error_task())

    # Keep the event loop alive
    while True:
        await asyncio.sleep(60)


asyncio.run(main())
