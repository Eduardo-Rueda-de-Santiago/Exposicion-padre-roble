"""
BLE Peripheral — ESP_COLUMN_N
==============================
Advertises this board's identity, notifies a central ESP32 of the latest
distance reading, and accepts LED configuration writes from that central.

GATT layout
───────────
Service  0x1234
  ├─ Characteristic 0x5678  READ | NOTIFY   → distance (UTF-8 float, e.g. "142.00")
  └─ Characteristic 0x5679  WRITE_NO_RSP    ← LED config JSON from central
                                               e.g. {"min_b":0,"max_b":255,
                                                      "min_d":50,"max_d":250}

UUIDs must match the central (ble_receiver / ble_central) firmware.

Connection states
─────────────────
  Disconnected : peripheral advertises continuously; distance is NOT sent
                 (no central to receive it) but sensor + LEDs keep running.
  Connected    : distance is notified every BLE_NOTIFY_INTERVAL_MS.
                 Config writes are accepted at any time and forwarded to
                 DataStorage for the LED task to apply.
"""

import bluetooth
import uasyncio as asyncio
import ujson
from common_data_storage import DataStorage
from micropython import const

# ---------------------------------------------------------------------------
# BLE UUIDs — must match the central firmware
# ---------------------------------------------------------------------------
_SERVICE_UUID = bluetooth.UUID(0x1234)
_CHAR_DISTANCE = bluetooth.UUID(0x5678)  # notify: distance readings
_CHAR_CONFIG = bluetooth.UUID(0x5679)  # write:  LED config from central

# ---------------------------------------------------------------------------
# GATT flags (module-level const — class-level const() breaks in MicroPython)
# ---------------------------------------------------------------------------
_FLAG_READ = const(0x0002)
_FLAG_NOTIFY = const(0x0010)
_FLAG_WRITE_NO_RSP = const(0x0004)

# ---------------------------------------------------------------------------
# BLE event codes used in the IRQ handler
# ---------------------------------------------------------------------------
_EVT_CENTRAL_CONNECT = const(1)
_EVT_CENTRAL_DISCONNECT = const(2)
_EVT_GATTS_WRITE = const(3)

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
# How often the distance is sent to the central when connected (ms).
# 500 ms matches the prototype; lower = more responsive, more radio traffic.
BLE_NOTIFY_INTERVAL_MS = const(500)

# GAP advertising interval in µs (100 ms)
_ADV_INTERVAL_US = const(100_000)


class BLEPeripheral:
    """
    BLE peripheral that:
      - Advertises as DEVICE_NAME (e.g. "ESP_COLUMN_1")
      - Notifies the central of the current distance every BLE_NOTIFY_INTERVAL_MS
      - Accepts JSON config writes and forwards them to DataStorage
    """

    def __init__(self, device_name: str, common_data_storage: DataStorage) -> None:
        """
        Args:
            device_name:          Advertised BLE name (e.g. "ESP_COLUMN_1").
            common_data_storage:  Shared state; distance is read from here,
                                  config writes are queued here for the LED task.
        """
        self._name = device_name
        self._ds = common_data_storage

        self._connected = False
        self._conn_handle = None

        # asyncio Events so other coroutines can await connection changes
        self.connected_event = asyncio.Event()
        self.disconnected_event = asyncio.Event()

        # Initialise BLE radio
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        # Register GATT service
        # gatts_register_services returns a nested tuple of handles matching
        # the structure passed in: ((dist_handle, cfg_handle),)
        ((self._handle_distance, self._handle_config),) = (
            self._ble.gatts_register_services(
                (
                    (
                        _SERVICE_UUID,
                        (
                            (_CHAR_DISTANCE, _FLAG_READ | _FLAG_NOTIFY),
                            (_CHAR_CONFIG, _FLAG_WRITE_NO_RSP),
                        ),
                    ),
                )
            )
        )

    # ───────────────────────── IRQ handler ─────────────────────────

    def _irq(self, event: int, data) -> None:
        """
        BLE IRQ — called from the radio stack, keep it fast.

        Events handled:
          1 – central connected
          2 – central disconnected  (auto-restarts advertising)
          3 – central wrote a characteristic (config payload)
        """
        if event == _EVT_CENTRAL_CONNECT:
            conn_handle, _addr_type, _addr = data
            self._conn_handle = conn_handle
            self._connected = True
            self.connected_event.set()
            self.disconnected_event.clear()
            print("[BLE] Central connected, handle={}".format(conn_handle))

        elif event == _EVT_CENTRAL_DISCONNECT:
            self._conn_handle = None
            self._connected = False
            self.disconnected_event.set()
            self.connected_event.clear()
            print("[BLE] Central disconnected — resuming advertising")
            self._advertise()  # Always re-advertise so central can reconnect

        elif event == _EVT_GATTS_WRITE:
            conn_handle, attr_handle = data
            if attr_handle == self._handle_config:
                # Read the raw bytes written by the central and hand them
                # to DataStorage.  DataStorage does the JSON parsing so the
                # IRQ returns as fast as possible.
                raw = self._ble.gatts_read(self._handle_config)
                self._ds.queue_led_config(raw)
                print("[BLE] Config received:", raw)

    # ───────────────────────── Advertising ─────────────────────────

    def _advertise(self) -> None:
        """Build a minimal AD structure and start GAP advertising."""
        name_bytes = self._name.encode("utf-8")
        flags = b"\x02\x01\x06"  # LE General Discoverable
        name_ad = bytes([len(name_bytes) + 1, 0x09]) + name_bytes  # Complete Local Name
        self._ble.gap_advertise(_ADV_INTERVAL_US, adv_data=flags + name_ad)

    def start(self) -> None:
        """Begin advertising. Call once before creating the async task."""
        print("[BLE] Advertising as '{}'".format(self._name))
        self._advertise()

    # ───────────────────────── Properties ─────────────────────────

    @property
    def connected(self) -> bool:
        """True while a central is connected."""
        return self._connected

    # ───────────────────────── Send helpers ─────────────────────────

    def _notify_distance(self, distance: int) -> None:
        """
        Push the distance value to the central as a UTF-8 string.

        Args:
            distance: Distance in cm.  Sent as e.g. "142.00" to match the
                      float format used by the HC-SR04 prototype so the same
                      central firmware can parse either sensor type.
        """
        if not self._connected or self._conn_handle is None:
            return
        payload = "{:.2f}".format(distance).encode("utf-8")
        self._ble.gatts_notify(self._conn_handle, self._handle_distance, payload)

    # ───────────────────────── Async task ─────────────────────────

    async def run_ble_async(self) -> None:
        """
        Async task entry point.

        Waits for a central to connect, then notifies the distance reading
        every BLE_NOTIFY_INTERVAL_MS.  Pauses automatically on disconnect
        and resumes on reconnection.  Config writes are handled in the IRQ
        and require no polling here.
        """
        while True:
            if not self._connected:
                print("[BLE] Waiting for central...")
                await self.connected_event.wait()
                print("[BLE] Connected — starting distance notifications")

            self._notify_distance(self._ds.distance_to_person)
            await asyncio.sleep_ms(BLE_NOTIFY_INTERVAL_MS)
