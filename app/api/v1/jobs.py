"""Job submission and status endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.core.lifespan import get_job_service
from app.models.job import JobStatus, TaskType
from app.schemas.job import (
    CreateJobRequest,
    JobCreatedResponse,
    JobDetailResponse,
    JobListResponse,
)
from app.services.job_service import (
    MAX_PAGE_SIZE,
    JobEnqueueError,
    JobNotFoundError,
    JobService,
)

router = APIRouter(prefix="/api/v1", tags=["jobs"])


def _validate_idempotency_key(idempotency_key: str | None) -> str | None:
    if idempotency_key is None:
        return None
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key header must not be empty",
        )
    if len(key) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key header must be at most 64 characters",
        )
    return key


@router.post(
    "/jobs",
    response_model=JobCreatedResponse,
    responses={
        status.HTTP_200_OK: {"model": JobCreatedResponse},
        status.HTTP_201_CREATED: {"model": JobCreatedResponse},
    },
)
async def create_job(
    body: CreateJobRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    job_service: JobService = Depends(get_job_service),
) -> JobCreatedResponse:
    """Accept a background job and enqueue it for processing."""
    validated_key = _validate_idempotency_key(idempotency_key)
    try:
        result = await job_service.create_job(body, idempotency_key=validated_key)
    except JobEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.reason,
        ) from exc

    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return JobCreatedResponse.model_validate(result.job)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    task_type: TaskType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    job_service: JobService = Depends(get_job_service),
) -> JobListResponse:
    """List jobs with optional status and task_type filters."""
    result = await job_service.list_jobs(
        status=status_filter,
        task_type=task_type,
        page=page,
        page_size=page_size,
    )
    return JobListResponse(
        items=[JobDetailResponse.model_validate(job) for job in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: UUID,
    job_service: JobService = Depends(get_job_service),
) -> JobDetailResponse:
    """Return the full status of a background job."""
    try:
        job = await job_service.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        ) from exc
    return JobDetailResponse.model_validate(job)
