"""FastAPI application entry point."""

import logging

from fastapi import FastAPI

from app import __version__
from app.api.v1.health import router as health_router
from app.core.lifespan import lifespan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def create_app() -> FastAPI:
    """Application factory used by uvicorn and tests."""
    app = FastAPI(
        title="Celery Task Pipeline API",
        description=(
            "Submit background jobs via API, track status in PostgreSQL, "
            "and execute work with Celery workers backed by Redis."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.include_router(health_router)

    return app


app = create_app()
