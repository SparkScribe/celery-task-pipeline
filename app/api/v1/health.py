"""Health check endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import __version__
from app.core.lifespan import get_redis_client, get_session_factory
from app.core.redis import RedisClient
from app.db.session import check_database_connectivity
from app.schemas.health import HealthResponse, ServiceStatus

router = APIRouter(tags=["health"])


def _aggregate_status(service_statuses: list[str]) -> str:
    if any(status == "unavailable" for status in service_statuses):
        if all(status == "unavailable" for status in service_statuses):
            return "unavailable"
        return "degraded"
    if any(status == "degraded" for status in service_statuses):
        return "degraded"
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health_check(
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    redis_client: RedisClient = Depends(get_redis_client),
) -> HealthResponse:
    """Return API health including Redis and PostgreSQL connectivity."""
    redis_status, redis_detail = await redis_client.check_connectivity()
    db_status, db_detail = await check_database_connectivity(session_factory)

    services = [
        ServiceStatus(name="redis", status=redis_status, detail=redis_detail),
        ServiceStatus(name="database", status=db_status, detail=db_detail),
    ]

    return HealthResponse(
        status=_aggregate_status([redis_status, db_status]),
        version=__version__,
        services=services,
    )
