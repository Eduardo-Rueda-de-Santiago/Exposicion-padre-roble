from fastapi import APIRouter
from pydantic import BaseModel
from services.video_player import video_service

video_router = APIRouter()

class PlayAllRequest(BaseModel):
    videos: list[str] = []

class ScreenPlayRequest(BaseModel):
    video: str = None

class VolumeRequest(BaseModel):
    volume: int = 100

@video_router.get("/status")
async def get_status():
    return video_service.get_status()

@video_router.get("/videos")
async def get_videos():
    return video_service.scan_videos()

@video_router.post("/play-all")
async def play_all(req: PlayAllRequest = None):
    videos = req.videos if req else None
    video_service.play_all(videos)
    return {"status": "playing"}

@video_router.post("/pause-all")
async def pause_all():
    video_service.pause_all()
    return {"status": "paused"}

@video_router.post("/resume-all")
async def resume_all():
    video_service.resume_all()
    return {"status": "playing"}

@video_router.post("/stop-all")
async def stop_all():
    video_service.stop_all()
    return {"status": "stopped"}

@video_router.post("/screen/{screen_id}/play")
async def play_screen(screen_id: int, req: ScreenPlayRequest = None):
    video = req.video if req else None
    video_service.play_screen(screen_id, video)
    return {"status": "playing"}

@video_router.post("/screen/{screen_id}/pause")
async def pause_screen(screen_id: int):
    video_service.pause_screen(screen_id)
    return {"status": "paused"}

@video_router.post("/screen/{screen_id}/resume")
async def resume_screen(screen_id: int):
    video_service.resume_screen(screen_id)
    return {"status": "playing"}

@video_router.post("/screen/{screen_id}/stop")
async def stop_screen(screen_id: int):
    video_service.stop_screen(screen_id)
    return {"status": "stopped"}

@video_router.post("/screen/{screen_id}/volume")
async def volume_screen(screen_id: int, req: VolumeRequest):
    video_service.set_volume_screen(screen_id, req.volume)
    return {"volume": req.volume}
