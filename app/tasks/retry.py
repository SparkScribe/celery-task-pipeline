"""Shared Celery task retry handling for job status updates."""

import uuid

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.models.job import JobStatus
from app.services.job_store import JobStore


def retry_countdown(retries: int) -> int:
    """Exponential backoff in seconds: 60, 120, 240, ..."""
    return 60 * (2**retries)


def fail_or_retry_task(
    task: Task,
    job_uuid: uuid.UUID,
    store: JobStore,
    exc: Exception,
) -> None:
    """Update job status and raise a Celery retry or propagate the error."""
    retries = task.request.retries
    retry_count = retries + 1
    max_retries = task.max_retries

    if retries >= max_retries:
        store.update_job(
            job_uuid,
            status=JobStatus.FAILED,
            error=str(exc),
            retry_count=retry_count,
        )
        raise exc

    store.update_job(
        job_uuid,
        status=JobStatus.RETRYING,
        error=str(exc),
        retry_count=retry_count,
    )
    try:
        raise task.retry(
            exc=exc,
            countdown=retry_countdown(retries),
            max_retries=max_retries,
        )
    except MaxRetriesExceededError:
        store.update_job(
            job_uuid,
            status=JobStatus.FAILED,
            error=str(exc),
            retry_count=retry_count,
        )
        raise exc from None
