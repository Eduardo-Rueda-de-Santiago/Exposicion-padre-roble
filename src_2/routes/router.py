import asyncio

from fastapi import APIRouter
from routes.audio_routes import audio_router
from routes.readings_routes import readings_router
from routes.sensor_routes import sensor_router
from routes.video_routes import video_router
from services.audio_player import audio_service
from services.database import db_service
from services.video_player import video_service

api_router = APIRouter(prefix="/api")
api_router.include_router(sensor_router, prefix="/sensors", tags=["Sensor"])
api_router.include_router(video_router, prefix="/video", tags=["Video"])
api_router.include_router(audio_router, prefix="/audio", tags=["Audio"])
api_router.include_router(readings_router, prefix="/readings", tags=["Readings"])


@api_router.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "api"}


@api_router.get("/status", tags=["Status"])
async def full_status():
    """Combines status endpoints for the frontend dashboard."""
    # All three service calls are synchronous — run them in a thread pool so
    # they don't block FastAPI's async event loop.
    conn_status, sensors, vm_status = await asyncio.gather(
        asyncio.to_thread(db_service.get_connection_status),
        asyncio.to_thread(db_service.get_all_sensors),
        asyncio.to_thread(video_service.get_status),
    )

    latest = await asyncio.gather(
        *[asyncio.to_thread(db_service.get_latest_reading, s) for s in sensors]
    )

    return {
        "serial_connected": conn_status["serial_connected"],
        "last_reading_time": conn_status["last_reading_time"],
        "readings_count": conn_status["readings_count"],
        "sensors": sensors,
        "latest": dict(zip(sensors, latest)),
        "video": vm_status,
    }


@api_router.post("/trigger-all", tags=["Global"])
async def trigger_all():
    """Triggers all videos and all audio columns simultaneously."""
    # Sensor IDs must match the string format used everywhere else: "ESP_COLUMN_N"
    sensor_ids = [f"ESP_COLUMN_{i}" for i in range(1, 9)]

    await asyncio.gather(
        asyncio.to_thread(video_service.play_all),
        asyncio.to_thread(audio_service.start),
    )
    await asyncio.gather(
        *[asyncio.to_thread(audio_service.trigger_sensor, sid) for sid in sensor_ids]
    )
    return {"status": "triggered_all"}


@api_router.post("/pause-all", tags=["Global"])
async def pause_all():
    """Pauses all videos and clears all audio triggers."""
    await asyncio.gather(
        asyncio.to_thread(video_service.pause_all),
        asyncio.to_thread(audio_service.stop),
    )
    return {"status": "paused_all"}


@api_router.post("/stop-all", tags=["Global"])
async def stop_all():
    """Stops all videos and clears all audio triggers."""
    await asyncio.gather(
        asyncio.to_thread(video_service.stop_all),
        asyncio.to_thread(audio_service.stop),
    )
    return {"status": "stopped_all"}
