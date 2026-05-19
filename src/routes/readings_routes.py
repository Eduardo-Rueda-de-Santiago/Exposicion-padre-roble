from fastapi import APIRouter
from services.database import db_service

readings_router = APIRouter()

@readings_router.get("/")
async def get_readings(limit: int = 100):
    return db_service.get_recent_readings(limit=limit)

@readings_router.get("/{sensor_id}")
async def get_readings_by_sensor(sensor_id: str, limit: int = 100):
    return db_service.get_recent_readings(limit=limit, sensor_id=sensor_id)
