"""
Entry point for the ESP32 proximity-lighting + BLE firmware.

Architecture
────────────────────────────────────────────────────────────
                      DataStorage  (shared state)
                           │
         ┌─────────────────┼──────────────────┐
         │                 │                  │
   MotionSensor       LedStripController   BLEPeripheral
   (handle_sensor)    (handle_led)         (handle_ble)
         │                 │                  │
         │  update_distance│                  │  notify distance →  Central ESP32
         └────────────────►│                  │◄─ config write  ←  Central ESP32
                           │  pop_led_config  │
                           └──────────────────┘

Task timing rationale
─────────────────────
  Sensor  — 50 ms sleep  : HMMD sensor outputs ~10 Hz; polling faster wastes
                           cycles and starves other tasks.
  LED     — 0 ms sleep   : yield-then-retry keeps brightness changes instant;
                           write() is only called when brightness changes.
  BLE     — 500 ms sleep : notifies central at ~2 Hz which is plenty for a
                           distance feed; BLE radio overhead is amortised.

BLE identity
────────────
  Change COLUMN_NUMBER to give each board a unique advertised name.
  The central firmware must scan for "ESP_COLUMN_N" and use the same UUIDs.
"""

import uasyncio as asyncio
from common_data_storage import DataStorage
from handle_ble import BLEPeripheral
from handle_led import LedStripController
from handle_sensor import MotionSensor

# ---------------------------------------------------------------------------
# Board identity — increment per physical column
# ---------------------------------------------------------------------------
COLUMN_NUMBER = 1
DEVICE_NAME = "ESP_COLUMN_{}".format(COLUMN_NUMBER)


async def main() -> None:
    # ── Shared state ────────────────────────────────────────────────────────
    ds = DataStorage()

    # ── Sensor task ─────────────────────────────────────────────────────────
    # Reads mmWave UART, writes ds.distance_to_person every ~50 ms.
    sensor = MotionSensor(ds, sensor_reading_wait_ms=50)

    # ── LED task ─────────────────────────────────────────────────────────────
    # Reads ds.distance_to_person and any pending BLE config every loop tick.
    # Hard-coded defaults are active from boot; BLE config overrides them
    # as soon as the central connects and sends a config write.
    led_controller = LedStripController(
        ds,
        min_distance_expected=50,
        max_distance_expected=250,
        min_brightness=0,
        max_brightness=255,
    )

    # ── BLE task ─────────────────────────────────────────────────────────────
    # Advertises as DEVICE_NAME, notifies distance, receives config writes.
    ble = BLEPeripheral(DEVICE_NAME, ds)
    ble.start()  # Begin advertising before creating the task

    # ── Launch all three tasks concurrently ─────────────────────────────────
    asyncio.create_task(sensor.run_sensor_async())
    asyncio.create_task(led_controller.run_led_async(update_interval_ms=0))
    asyncio.create_task(ble.run_ble_async())

    # Keep the event loop alive; add future top-level tasks here.
    while True:
        await asyncio.sleep_ms(100)


asyncio.run(main())
