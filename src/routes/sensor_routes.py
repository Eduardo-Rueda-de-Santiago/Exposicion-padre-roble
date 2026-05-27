import json
import os

from fastapi import APIRouter, Request

from services.database import db_service

# from services.audio_player import audio_service
from services.serial_reader import serial_reader_service

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


@sensor_router.get("/config")
async def get_config():
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "sensor_audio_map.json"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


@sensor_router.post("/config")
async def save_config(request: Request):
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "sensor_audio_map.json"
    )
    try:
        new_config = await request.json()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2)

        # Reload services to apply the new configuration
        # audio_service.reload_config()
        serial_reader_service.reload_config()

        return {"status": "success", "message": "Configuration updated successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
