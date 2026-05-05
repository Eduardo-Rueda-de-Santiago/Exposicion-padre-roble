from fastapi import APIRouter
from routes.audio_routes import audio_router
from routes.readings_routes import readings_router
from routes.sensor_routes import sensor_router
from routes.video_routes import video_router

api_router = APIRouter(prefix="/api")

api_router.include_router(sensor_router, prefix="/sensor", tags=["Sensor"])
api_router.include_router(video_router, prefix="/video", tags=["Video"])
api_router.include_router(audio_router, prefix="/audio", tags=["Audio"])
api_router.include_router(readings_router, prefix="/readings", tags=["Readings"])


@api_router.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Service status and basic metadata.

    Use cases:
    - Load balancer health checks
    - Kubernetes liveness/readiness probes
    - Monitoring systems
    """
    return {
        "status": "ok",
        "service": "api",
    }
