from fastapi import APIRouter
from services.audio_player import audio_service

audio_router = APIRouter()

@audio_router.post("/trigger/{column_id}")
async def trigger_audio(column_id: int):
    audio_service.trigger_column(column_id)
    return {"status": "triggered", "column": column_id}
