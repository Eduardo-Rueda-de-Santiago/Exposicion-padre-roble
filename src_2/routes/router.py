from fastapi import APIRouter
from routes.audio_routes import audio_router
from routes.readings_routes import readings_router
from routes.sensor_routes import sensor_router
from routes.video_routes import video_router
from services.database import db_service
from services.video_player import video_service

api_router = APIRouter(prefix="/api")

api_router.include_router(sensor_router, prefix="/sensors", tags=["Sensor"])
api_router.include_router(video_router, prefix="/video", tags=["Video"])
api_router.include_router(audio_router, prefix="/audio", tags=["Audio"])
api_router.include_router(readings_router, prefix="/readings", tags=["Readings"])


@api_router.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Service status and basic metadata.
    """
    return {
        "status": "ok",
        "service": "api",
    }

@api_router.get("/status", tags=["Status"])
async def full_status():
    """
    Combines status endpoints for the frontend dashboard.
    """
    conn_status = db_service.get_connection_status()
    sensors = db_service.get_all_sensors()
    latest = {s: db_service.get_latest_reading(s) for s in sensors}
    vm_status = video_service.get_status()
    
    return {
        "serial_connected": conn_status['serial_connected'],
        "last_reading_time": conn_status['last_reading_time'],
        "readings_count": conn_status['readings_count'],
        "sensors": sensors,
        "latest": latest,
        "video": vm_status,
    }
