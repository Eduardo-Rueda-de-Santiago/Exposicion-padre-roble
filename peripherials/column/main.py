"""
Entry point for the ESP32 proximity-lighting firmware.

Architecture
────────────
DataStorage (shared state)
    ↑ writes distance         ↓ reads distance
MotionSensor task       LedStripController task

"""

import uasyncio as asyncio
from common_data_storage import DataStorage
from handle_led import LedStripController
from handle_sensor import MotionSensor


async def main() -> None:
    # Shared state — single source of truth for the current distance
    ds = DataStorage()

    # Sensor task: reads UART, writes ds.distance_to_person
    sensor = MotionSensor(ds, sensor_reading_wait_ms=15)

    # LED task: reads ds.distance_to_person, drives the NeoPixel strip
    led_controller = LedStripController(ds)

    # Schedule both coroutines as concurrent tasks
    asyncio.create_task(sensor.run_sensor_async())
    asyncio.create_task(led_controller.run_led_async(update_interval_ms=0))

    # Keep the event loop alive; add any future top-level tasks here
    while True:
        await asyncio.sleep_ms(100)
        print(f"Dist: {ds.distance_to_person}")
        print(f"Bright: {led_controller.target_led_brightness}")


asyncio.run(main())
