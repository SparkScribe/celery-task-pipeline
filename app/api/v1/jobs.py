"""Job submission and status endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.lifespan import get_job_service
from app.schemas.job import CreateJobRequest, JobCreatedResponse, JobDetailResponse
from app.services.job_service import JobEnqueueError, JobNotFoundError, JobService

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.post("/jobs", response_model=JobCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    job_service: JobService = Depends(get_job_service),
) -> JobCreatedResponse:
    """Accept a background job and enqueue it for processing."""
    try:
        job = await job_service.create_job(body)
    except JobEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.reason,
        ) from exc
    return JobCreatedResponse.model_validate(job)


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
