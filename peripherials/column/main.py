from asyncio import create_task, run, sleep_ms

from common_data_storage import DataStorage
from handle_led import LedStripController
from handle_sensor import MotionSensor

ds = DataStorage()
# led_controller = LedStripController()


# async def update_leds():
#     led_controller.update_led_brightness(ds.distance_to_person)
#     print(ds.distance_to_person)
#     sleep_ms(10)


async def main():
    sensor = MotionSensor(ds, sensor_reading_wait_ms=10)

    create_task(sensor.run_sensor_async())
    #     create_task(update_leds())

    while True:
        await sleep_ms(10)  # keep loop alive
        print(ds.distance_to_person)


#
run(main())
