from fastapi import APIRouter
from services.database import db_service

sensor_router = APIRouter()

@sensor_router.get("/")
async def get_sensors():
    return db_service.get_all_sensors()

@sensor_router.get("/latest")
async def get_latest():
    sensors = db_service.get_all_sensors()
    result = {}
    for s in sensors:
        reading = db_service.get_latest_reading(s)
        if reading:
            result[s] = reading
    return result
