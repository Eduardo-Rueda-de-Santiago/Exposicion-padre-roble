import uvicorn
from fastapi import FastAPI
from routes.router import api_router  # your router file


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """
    app = FastAPI(
        title="API expo padre roble.",
        version="1.0.0",
        description="Api local usada para gestionar la expo padre roble.",
    )

    app.include_router(api_router)
    return app


def run_server(port: int = 8000) -> None:
    """
    Run the FastAPI server locally.

    Args:
        port (int): Port to bind the server to (default: 8000)
    """
    app = create_app()

    uvicorn.run(
        app,
        host="127.0.0.1",  # localhost only
        port=port,
        reload=True,  # auto-reload for development
    )


if __name__ == "__main__":
    run_server(8000)
