import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from routes.router import api_router
from services.audio_player import audio_service
from services.database import db_service
from services.serial_reader import serial_reader_service
from services.video_player import video_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[WEB] Initializing application services...")
    db_service.init_db()
    serial_reader_service.start()
    yield
    # Shutdown
    print("[WEB] Shutting down application services...")
    serial_reader_service.stop()
    audio_service.stop()
    video_service.cleanup()


def create_app() -> FastAPI:
    app = FastAPI(
        title="API expo padre roble.",
        version="1.0.0",
        description="Api local usada para gestionar la expo padre roble.",
        lifespan=lifespan,
    )

    app.include_router(api_router)

    # Mount static files and templates
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")

    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    templates = Jinja2Templates(directory=templates_dir)

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    return app


def run_server(port: int = 8000) -> None:
    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    run_server(8000)
