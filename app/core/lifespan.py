"""Application lifespan and shared dependency injection."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.redis import RedisClient
from app.db.session import create_async_db_engine, create_session_factory, init_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services on startup and clean up on shutdown."""
    settings = get_settings()
    engine = create_async_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    redis_client = RedisClient(settings)

    try:
        await init_database(engine)
        logger.info("Database initialized at %s", settings.database_url.split("@")[-1])
    except Exception:
        logger.exception(
            "Failed to initialize database — health will report degraded until resolved",
        )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis_client = redis_client

    yield

    await redis_client.close()
    await engine.dispose()
    logger.info("Application shutdown complete")


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def get_redis_client(request: Request) -> RedisClient:
    return request.app.state.redis_client
