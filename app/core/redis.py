"""Redis client wrapper for connectivity checks and caching."""

import logging

import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Thin async Redis wrapper used for health checks and future features."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: aioredis.Redis | None = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._client

    async def check_connectivity(self) -> tuple[str, str | None]:
        """Ping Redis and return a status tuple."""
        try:
            pong = await self._get_client().ping()
            if pong:
                return "ok", "PONG"
            return "degraded", "Unexpected ping response"
        except Exception as exc:
            logger.warning("Redis connectivity check failed: %s", exc)
            return "unavailable", str(exc)

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
