"""
BLE Central — Aggregator ESP32
================================
Scans for and connects to up to 8 peripherals named ESP_COLUMN_<N>.
Forwards distance notifications to the connected computer over USB serial
in the format the peripheral already sends:
    ESP_COLUMN_1|142.00

Config forwarding (computer → peripheral) is stubbed and ready to extend:
    Incoming serial format:
        {"target": "ESP_COLUMN_1", "min_brightness": 0, "max_brightness": 255,
         "min_distance": 50, "max_distance": 250}
    All keys except "target" are optional.
    Implementation: write the config JSON (minus "target") to characteristic
    0x5679 on the target peripheral once that path is wired up.

GATT layout expected on each peripheral (must match handle_ble.py):
    Service  0x1234
      ├─ 0x5678  READ | NOTIFY  ← distance forwarded to serial
      └─ 0x5679  WRITE_NO_RSP  → config (future — not written yet)

Task model
──────────
  led_task         : Blinks LED reflecting global connection state.
  scan_task        : Periodic BLE scan + connection attempts every
                     SCAN_INTERVAL_S seconds.
  rx_task          : One per connected peripheral; forwards notifications
                     to serial.
  error_task       : Monitors failed devices, reports + retries every
                     RECONNECT_INTERVAL_S seconds.
  serial_read_task : Reads lines from USB serial; parses config JSON and
                     logs it. Routing to peripherals is stubbed for later.
"""

import bluetooth
import uasyncio as asyncio
import ujson
from micropython import const

try:
    from machine import UART, Pin

    _uart = UART(0, baudrate=115200)  # USB-serial on most ESP32 builds
except Exception:
    _uart = None

# ---------------------------------------------------------------------------
# UUIDs — must match handle_ble.py on each peripheral
# ---------------------------------------------------------------------------
SERVICE_UUID = bluetooth.UUID(0x1234)
CHAR_DISTANCE_UUID = bluetooth.UUID(0x5678)  # subscribe to notifications
CHAR_CONFIG_UUID = bluetooth.UUID(0x5679)  # future: write config here

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
SCAN_INTERVAL_S = const(10)  # Re-scan for new / lost devices
RECONNECT_INTERVAL_S = const(60)  # Slow-retry period after repeated failures
MAX_RECONNECT_FAST = const(5)  # Failures before dropping to 1/min retry
CONNECT_TIMEOUT_S = const(5)  # Max wait per connection attempt
SCAN_DURATION_MS = const(3_000)  # BLE scan window

BLINK_DISCONNECTED = 0.05  # LED blink period when no devices connected (s)
BLINK_CONNECTED = 1.0  # LED blink period when ≥1 device connected (s)

# Expected column name prefix
_COL_PREFIX = "ESP_COLUMN_"

# ---------------------------------------------------------------------------
# LED helpers
# ---------------------------------------------------------------------------
try:
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
# Serial I/O
# ---------------------------------------------------------------------------
def serial_print(msg: str) -> None:
    """Send a line to the computer over USB serial (and local console)."""
    print(msg)


def serial_readline() -> str | None:
    """
    Non-blocking read of one line from USB serial.
    Returns the stripped string if a complete line is available, else None.
    MicroPython's UART.readline() returns None when no data is waiting.
    """
    if _uart is None:
        return None
    line = _uart.readline()
    if line:
        try:
            return line.decode("utf-8").strip()
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Device name validation
# ---------------------------------------------------------------------------
def is_column_device(name: str) -> bool:
    """Accept only ESP_COLUMN_<integer> names."""
    if not name.startswith(_COL_PREFIX):
        return False
    suffix = name[len(_COL_PREFIX) :]
    return suffix.isdigit()


# ---------------------------------------------------------------------------
# Device state
# ---------------------------------------------------------------------------
class DeviceInfo:
    """Tracks connection state and notification buffer for one peripheral."""

    def __init__(self, name: str, addr: bytes, addr_type: int) -> None:
        self.name = name
        self.addr = addr
        self.addr_type = addr_type
        self.connected = False
        self.conn_handle: int | None = None
        self.fail_count = 0

        # Handle for the distance characteristic (filled after GATT discovery)
        self.distance_value_handle: int | None = None

        # asyncio.Event signals rx_task that a notification arrived
        self.rx_event = asyncio.Event()
        # Notification payloads waiting to be printed — list acts as a queue
        self.rx_buffer = []


# Global device registry  { name: DeviceInfo }
devices: dict = {}


# ---------------------------------------------------------------------------
# BLE Central
# ---------------------------------------------------------------------------
class BLECentral:
    """
    Manages scanning, connecting, GATT discovery, and notification receipt
    for all ESP_COLUMN peripherals.
    """

    def __init__(self) -> None:
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        # Scan results filled by IRQ, consumed by scan_task
        self._scan_results: dict = {}  # addr_hex → {name, addr, addr_type}
        self._scan_done = asyncio.Event()

        # addr_hex → device name, for pending (in-flight) connections
        self._pending: dict = {}

    # ──────────────────────────── IRQ ────────────────────────────────

    def _irq(self, event: int, data) -> None:
        """
        BLE IRQ — runs in radio-stack context; must be fast with no allocations.

        Events handled:
            5  – scan result
            6  – scan complete
            7  – peripheral connected   (as central)
            8  – peripheral disconnected
            9  – GATT service result
            11 – GATT characteristic result
            18 – notification received
        """

        # ── Scan result ──────────────────────────────────────────────
        if event == 5:
            addr_type, addr, _adv_type, _rssi, adv_data = data
            name = self._decode_name(bytes(adv_data))
            if name and is_column_device(name):
                addr_hex = bytes(addr).hex()
                self._scan_results[addr_hex] = {
                    "name": name,
                    "addr": bytes(addr),
                    "addr_type": addr_type,
                }

        # ── Scan complete ─────────────────────────────────────────────
        elif event == 6:
            self._scan_done.set()

        # ── Peripheral connected ──────────────────────────────────────
        elif event == 7:
            conn_handle, addr_type, addr = data
            addr_hex = bytes(addr).hex()
            name = self._pending.pop(addr_hex, None)
            if name and name in devices:
                dev = devices[name]
                dev.connected = True
                dev.conn_handle = conn_handle
                dev.fail_count = 0
                # Kick off GATT service discovery so we can find the
                # distance characteristic handle and subscribe to it
                self._ble.gattc_discover_services(conn_handle)

        # ── Peripheral disconnected ───────────────────────────────────
        elif event == 8:
            conn_handle, _addr_type, _addr = data
            for dev in devices.values():
                if dev.conn_handle == conn_handle:
                    dev.connected = False
                    dev.conn_handle = None
                    dev.distance_value_handle = None
                    break

        # ── GATT service result ───────────────────────────────────────
        elif event == 9:
            conn_handle, start_handle, end_handle, uuid = data
            if bluetooth.UUID(uuid) == SERVICE_UUID:
                # Discover characteristics within our service range
                self._ble.gattc_discover_characteristics(
                    conn_handle, start_handle, end_handle
                )

        # ── GATT characteristic result ────────────────────────────────
        elif event == 11:
            conn_handle, _def_handle, value_handle, _properties, uuid = data
            if bluetooth.UUID(uuid) == CHAR_DISTANCE_UUID:
                # Store the value handle so rx_task can cross-reference it,
                # then enable notifications by writing 0x0001 to the CCCD
                # (Client Characteristic Configuration Descriptor = handle + 1)
                for dev in devices.values():
                    if dev.conn_handle == conn_handle:
                        dev.distance_value_handle = value_handle
                        break
                self._ble.gattc_write(conn_handle, value_handle + 1, b"\x01\x00", 1)

        # ── Notification received ─────────────────────────────────────
        elif event == 18:
            conn_handle, value_handle, notify_data = data
            payload = bytes(notify_data)
            for dev in devices.values():
                if dev.conn_handle == conn_handle:
                    dev.rx_buffer.append(payload)
                    dev.rx_event.set()
                    break

    # ──────────────────────────── Helpers ────────────────────────────

    @staticmethod
    def _decode_name(adv_data: bytes) -> str | None:
        """Extract Complete or Shortened Local Name from raw AD bytes."""
        i = 0
        while i < len(adv_data):
            length = adv_data[i]
            if length == 0:
                break
            ad_type = adv_data[i + 1]
            if ad_type in (0x08, 0x09):  # Shortened / Complete Local Name
                try:
                    return adv_data[i + 2 : i + 1 + length].decode("utf-8")
                except Exception:
                    return None
            i += 1 + length
        return None

    # ──────────────────────────── Public async API ────────────────────

    async def scan(self) -> dict:
        """
        Run a BLE scan for SCAN_DURATION_MS ms.

        Returns:
            Dict of addr_hex → {name, addr, addr_type} for allowed devices found.
        """
        self._scan_results.clear()
        self._scan_done.clear()
        self._ble.gap_scan(SCAN_DURATION_MS, 30_000, 30_000)
        try:
            await asyncio.wait_for(self._scan_done.wait(), SCAN_DURATION_MS / 1000 + 1)
        except asyncio.TimeoutError:
            self._ble.gap_scan(None)  # Force-stop if event never fired
        return dict(self._scan_results)

    async def connect(self, dev: DeviceInfo) -> bool:
        """
        Initiate a connection to dev and wait up to CONNECT_TIMEOUT_S seconds.

        Returns:
            True if connected, False on timeout.
        """
        addr_hex = dev.addr.hex()
        self._pending[addr_hex] = dev.name
        self._ble.gap_connect(dev.addr_type, dev.addr)

        for _ in range(CONNECT_TIMEOUT_S * 10):  # Poll every 100 ms
            await asyncio.sleep_ms(100)
            if dev.connected:
                return True

        self._pending.pop(addr_hex, None)
        return False


# Singleton central
central = BLECentral()


# ---------------------------------------------------------------------------
# Task: LED blinker
# ---------------------------------------------------------------------------
async def led_task() -> None:
    """Blinks the onboard LED: fast when searching, slow when ≥1 device up."""
    while True:
        any_up = any(dev.connected for dev in devices.values())
        period = BLINK_CONNECTED if any_up else BLINK_DISCONNECTED
        led_on()
        await asyncio.sleep(period / 2)
        led_off()
        await asyncio.sleep(period / 2)


# ---------------------------------------------------------------------------
# Task: per-device RX
# ---------------------------------------------------------------------------
async def rx_task(dev: DeviceInfo) -> None:
    """
    Receives BLE notifications from one peripheral and forwards them to serial.

    The peripheral sends: "ESP_COLUMN_1|142.00"
    This task prints that string as-is with serial_print().

    Exits cleanly on disconnect so scan_task / error_task can restart it.
    """
    serial_print("[INFO] rx_task started for {}".format(dev.name))

    while dev.connected:
        try:
            await asyncio.wait_for(dev.rx_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue  # Re-check dev.connected

        dev.rx_event.clear()

        while dev.rx_buffer:
            payload = dev.rx_buffer.pop(0)
            try:
                message = payload.decode("utf-8").strip()
            except Exception:
                message = payload.hex()
            serial_print(message)  # Forward as-is: "ESP_COLUMN_1|142.00"

    serial_print("[INFO] rx_task exiting for {} (disconnected)".format(dev.name))


# ---------------------------------------------------------------------------
# Task: scan + connection manager
# ---------------------------------------------------------------------------
async def scan_task() -> None:
    """
    Every SCAN_INTERVAL_S: scan for ESP_COLUMN_<N> devices not yet connected
    and attempt to connect.  Spawns a fresh rx_task on each success.
    """
    rx_active: set = set()  # Names with a currently live rx_task

    while True:
        serial_print("[SCAN] Scanning for ESP_COLUMN devices...")
        found = await central.scan()

        for addr_hex, info in found.items():
            name = info["name"]

            if name not in devices:
                devices[name] = DeviceInfo(name, info["addr"], info["addr_type"])
                serial_print("[SCAN] Discovered: {}".format(name))

            dev = devices[name]

            if dev.connected:
                if name not in rx_active:
                    asyncio.create_task(rx_task(dev))
                    rx_active.add(name)
                continue

            # Devices past the fast-retry limit are handled by error_task
            if dev.fail_count >= MAX_RECONNECT_FAST:
                continue

            serial_print("[SCAN] Connecting to {}...".format(name))
            success = await central.connect(dev)

            if success:
                serial_print("[INFO] Connected to {}".format(name))
                asyncio.create_task(rx_task(dev))
                rx_active.add(name)
            else:
                dev.fail_count += 1
                serial_print(
                    "[WARN] Failed to connect to {} (attempt {})".format(
                        name, dev.fail_count
                    )
                )

        # Prune names whose rx_task has exited
        rx_active = {n for n in rx_active if n in devices and devices[n].connected}

        await asyncio.sleep(SCAN_INTERVAL_S)


# ---------------------------------------------------------------------------
# Task: error reporter + slow reconnect
# ---------------------------------------------------------------------------
async def error_task() -> None:
    """
    Every RECONNECT_INTERVAL_S: report and attempt one reconnect for any device
    that has exceeded MAX_RECONNECT_FAST consecutive failures.
    """
    while True:
        await asyncio.sleep(RECONNECT_INTERVAL_S)

        for dev in list(devices.values()):
            if dev.connected or dev.fail_count < MAX_RECONNECT_FAST:
                continue

            serial_print(
                "[ERROR] {} unreachable after {} failed attempts.".format(
                    dev.name, dev.fail_count
                )
            )
            serial_print("[RETRY] Attempting reconnect to {}...".format(dev.name))

            success = await central.connect(dev)

            if success:
                dev.fail_count = 0
                serial_print("[INFO] Reconnected to {}.".format(dev.name))
                asyncio.create_task(rx_task(dev))
            else:
                dev.fail_count += 1
                serial_print(
                    "[ERROR] Reconnect failed for {}. Total attempts: {}.".format(
                        dev.name, dev.fail_count
                    )
                )


# ---------------------------------------------------------------------------
# Task: serial reader (config ingestion — forwarding stubbed for later)
# ---------------------------------------------------------------------------

# Full config key names accepted from the computer.
# Maps to the short keys expected by DataStorage.queue_led_config() on
# the peripheral.  Extend this dict when forwarding is implemented.
_CONFIG_KEY_REMAP = {
    "min_brightness": "min_b",
    "max_brightness": "max_b",
    "min_distance": "min_d",
    "max_distance": "max_d",
}


async def serial_read_task() -> None:
    """
    Reads newline-terminated JSON config commands from the computer over USB
    serial and logs them.

    Expected format:
        {"target": "ESP_COLUMN_1", "min_brightness": 0, "max_brightness": 255,
         "min_distance": 50, "max_distance": 250}

    "target" is required; all other keys are optional.

    TODO (when config forwarding is ready):
        1. Look up devices[target] to get the conn_handle.
        2. Remap long key names to short ones using _CONFIG_KEY_REMAP.
        3. Serialise the config subset back to JSON bytes.
        4. Call central._ble.gattc_write(conn_handle,
               dev.config_value_handle, config_bytes, 1)
           where dev.config_value_handle is populated during GATT discovery
           for CHAR_CONFIG_UUID (0x5679).
    """
    serial_print("[SERIAL] Config reader started — awaiting commands.")

    while True:
        line = serial_readline()

        if line:
            try:
                payload = ujson.loads(line)
            except Exception:
                serial_print("[SERIAL] Invalid JSON, ignored: {}".format(line))
                await asyncio.sleep_ms(10)
                continue

            target = payload.get("target")
            if not target:
                serial_print("[SERIAL] Missing 'target' key, ignored.")
                await asyncio.sleep_ms(10)
                continue

            # Extract and remap config keys, drop "target" itself
            config = {}
            for long_key, short_key in _CONFIG_KEY_REMAP.items():
                if long_key in payload:
                    config[short_key] = payload[long_key]

            if not config:
                serial_print(
                    "[SERIAL] No recognised config keys for {}.".format(target)
                )
                await asyncio.sleep_ms(10)
                continue

            serial_print(
                "[SERIAL] Config for {}: {} — forwarding not yet implemented.".format(
                    target, config
                )
            )
            # TODO: forward config to target peripheral via BLE write

        await asyncio.sleep_ms(10)  # Yield; check serial ~100x per second


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    serial_print("[BOOT] BLE Central starting...")
    serial_print("[BOOT] Scanning for ESP_COLUMN_<N> peripherals")
    serial_print("[BOOT] SERVICE_UUID       = 0x1234")
    serial_print("[BOOT] CHAR_DISTANCE_UUID = 0x5678")
    serial_print("[BOOT] CHAR_CONFIG_UUID   = 0x5679  (write — future)")

    asyncio.create_task(led_task())
    asyncio.create_task(scan_task())
    asyncio.create_task(error_task())
    asyncio.create_task(serial_read_task())

    while True:
        await asyncio.sleep(10)


asyncio.run(main())
