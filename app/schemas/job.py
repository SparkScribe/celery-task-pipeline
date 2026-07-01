"""Job API request and response schemas."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.models.job import JobStatus, TaskType


class ProcessDataPayload(BaseModel):
    """Payload for the process_data task."""

    input_text: str = Field(min_length=1, max_length=10_000)
    delay_seconds: int = Field(default=0, ge=0, le=30)


class SendWebhookPayload(BaseModel):
    """Payload for the send_webhook task."""

    url: HttpUrl
    body: dict[str, Any] = Field(default_factory=dict)


class CreateJobRequest(BaseModel):
    """Body for POST /api/v1/jobs."""

    task_type: TaskType
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload_for_task_type(self) -> Self:
        if self.task_type == TaskType.PROCESS_DATA:
            validated = ProcessDataPayload.model_validate(self.payload)
        elif self.task_type == TaskType.SEND_WEBHOOK:
            validated = SendWebhookPayload.model_validate(self.payload)
        else:
            raise ValueError(f"Unsupported task_type: {self.task_type}")
        self.payload = validated.model_dump(mode="json")
        return self


class JobCreatedResponse(BaseModel):
    """Response returned when a job is accepted."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: JobStatus
    task_type: TaskType
    created_at: datetime


class JobDetailResponse(BaseModel):
    """Full job record returned by GET /api/v1/jobs/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    idempotency_key: str | None
    task_type: TaskType
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    retry_count: int
    celery_task_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("task_type", mode="before")
    @classmethod
    def coerce_task_type(cls, value: str | TaskType) -> TaskType:
        if isinstance(value, TaskType):
            return value
        return TaskType(value)

    @field_validator("status", mode="before")
    @classmethod
    def coerce_status(cls, value: str | JobStatus) -> JobStatus:
        if isinstance(value, JobStatus):
            return value
        return JobStatus(value)


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    items: list[JobDetailResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)
