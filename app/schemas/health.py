"""Health check response schemas."""

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """Status of an individual downstream dependency."""

    name: str
    status: str = Field(description="ok | degraded | unavailable")
    detail: str | None = None


class HealthResponse(BaseModel):
    """Aggregated health check response."""

    status: str = Field(description="ok | degraded | unavailable")
    version: str
    services: list[ServiceStatus]
