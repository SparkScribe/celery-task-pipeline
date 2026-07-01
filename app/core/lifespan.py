"""Application lifespan and shared dependency injection."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.redis import RedisClient
from app.db.session import create_async_db_engine, create_session_factory, init_database
from app.services.job_service import JobService
from app.services.task_dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services on startup and clean up on shutdown."""
    settings = get_settings()
    engine = create_async_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    redis_client = RedisClient(settings)
    task_dispatcher = TaskDispatcher(celery_app)

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
    app.state.task_dispatcher = task_dispatcher

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


def get_task_dispatcher(request: Request) -> TaskDispatcher:
    return request.app.state.task_dispatcher


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_job_service(
    session: AsyncSession = Depends(get_db_session),
    task_dispatcher: TaskDispatcher = Depends(get_task_dispatcher),
) -> JobService:
    return JobService(session=session, task_dispatcher=task_dispatcher)
