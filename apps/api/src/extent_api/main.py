"""FastAPI application boundary."""

from fastapi import FastAPI

from extent_api import __version__
from extent_api.routers.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Extent API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.include_router(health_router)
    return app


app = create_app()
