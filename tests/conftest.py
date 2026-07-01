"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.redis import RedisClient
from app.db.session import create_session_factory, init_database
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/1",
    )


@pytest.fixture
def mock_redis_client() -> MagicMock:
    client = MagicMock(spec=RedisClient)
    client.check_connectivity = AsyncMock(return_value=("ok", "PONG"))
    client.close = AsyncMock(return_value=None)
    return client


@pytest.fixture
def client(
    settings: Settings,
    mock_redis_client: MagicMock,
) -> Generator[TestClient, None, None]:
    engine = create_async_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        await init_database(engine)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.redis_client = mock_redis_client
        yield
        await engine.dispose()

    app = create_app()
    app.router.lifespan_context = test_lifespan

    with TestClient(app) as test_client:
        yield test_client
