from asyncio import run

from handle_sensor import MotionSensor

run(MotionSensor(sensor_reading_wait_ms=100).run_sensor_async())
