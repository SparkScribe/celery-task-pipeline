"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Celery Task Pipeline API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/celery_pipeline",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(
        default="redis://localhost:6379/0",
        alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1",
        alias="CELERY_RESULT_BACKEND",
    )

    # Celery task defaults
    celery_task_max_retries: int = Field(default=3, ge=0, le=10)
    webhook_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    process_data_max_delay_seconds: int = Field(default=30, ge=0, le=300)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
