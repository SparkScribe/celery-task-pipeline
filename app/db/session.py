"""Async database engine and session factory."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base


def ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create parent directory for file-backed SQLite databases."""
    if not database_url.startswith("sqlite+aiosqlite:///./"):
        return
    db_path = database_url.removeprefix("sqlite+aiosqlite:///./")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def create_async_db_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given database URL."""
    ensure_sqlite_parent_dir(database_url)
    if database_url in {"sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite://"}:
        return create_async_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_async_engine(database_url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the given engine."""
    return async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def init_database(engine: AsyncEngine) -> None:
    """Create database tables for all registered ORM models."""
    import app.models  # noqa: F401 — register ORM models with metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_database_connectivity(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str | None]:
    """Verify database connectivity with a lightweight query."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return "ok", "connected"
    except Exception as exc:
        return "unavailable", str(exc)


async def get_async_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session and close it when done."""
    async with session_factory() as session:
        yield session
