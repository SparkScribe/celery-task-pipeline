"""Synchronous database engine for Celery workers."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings

_sync_engine: Engine | None = None
_sync_session_factory: sessionmaker[Session] | None = None


def _sqlite_connect_args(database_url: str) -> dict[str, bool]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def create_sync_db_engine(settings: Settings | None = None) -> Engine:
    """Create a synchronous SQLAlchemy engine for worker processes."""
    resolved_settings = settings or get_settings()
    database_url = resolved_settings.sync_database_url
    if database_url in {"sqlite:///:memory:", "sqlite://"}:
        return create_engine(
            database_url,
            connect_args=_sqlite_connect_args(database_url),
            poolclass=StaticPool,
        )
    return create_engine(
        database_url,
        connect_args=_sqlite_connect_args(database_url),
    )


def get_sync_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """Return a cached sync session factory for workers."""
    global _sync_engine, _sync_session_factory
    if _sync_session_factory is None:
        _sync_engine = create_sync_db_engine(settings)
        _sync_session_factory = sessionmaker(
            bind=_sync_engine,
            autoflush=False,
            autocommit=False,
        )
    return _sync_session_factory


def reset_sync_session_factory() -> None:
    """Dispose cached sync engine state (used in tests)."""
    global _sync_engine, _sync_session_factory
    if _sync_engine is not None:
        _sync_engine.dispose()
    _sync_engine = None
    _sync_session_factory = None
