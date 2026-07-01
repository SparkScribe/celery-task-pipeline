"""process_data Celery task implementation."""

import logging
import time
import uuid
from typing import Any

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.models.job import JobStatus
from app.services.job_store import JobNotFoundError, JobStore

logger = logging.getLogger(__name__)

TASK_NAME = "app.tasks.process_data.process_data_task"


class ProcessDataError(Exception):
    """Raised when process_data execution fails."""


def run_process_data(payload: dict[str, Any], *, max_delay_seconds: int = 30) -> dict[str, Any]:
    """Transform input text after an optional delay."""
    input_text = payload.get("input_text")
    if not isinstance(input_text, str) or not input_text:
        raise ProcessDataError("payload.input_text is required")

    delay_seconds = payload.get("delay_seconds", 0)
    if not isinstance(delay_seconds, int) or delay_seconds < 0:
        raise ProcessDataError("payload.delay_seconds must be a non-negative integer")

    capped_delay = min(delay_seconds, max_delay_seconds)
    if capped_delay:
        time.sleep(capped_delay)

    return {
        "output_text": input_text.upper(),
        "word_count": len(input_text.split()),
    }


def execute_process_data(job_id: uuid.UUID, job_store: JobStore | None = None) -> dict[str, Any]:
    """Load a job, mark it running, execute process_data, and persist the result."""
    store = job_store or JobStore()
    settings = get_settings()

    job = store.get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    store.update_job(job_id, status=JobStatus.RUNNING, clear_error=True)
    result = run_process_data(
        job.payload,
        max_delay_seconds=settings.process_data_max_delay_seconds,
    )
    store.update_job(job_id, status=JobStatus.SUCCEEDED, result=result, clear_error=True)
    return result


def _retry_countdown(retries: int) -> int:
    """Exponential backoff in seconds: 60, 120, 240, ..."""
    return 60 * (2**retries)


@celery_app.task(bind=True, name=TASK_NAME, max_retries=get_settings().celery_task_max_retries)
def process_data_task(self: Task, job_id: str) -> dict[str, Any]:
    """Celery entrypoint for the process_data job type."""
    store = JobStore()
    job_uuid = uuid.UUID(job_id)

    try:
        return execute_process_data(job_uuid, store)
    except JobNotFoundError:
        logger.error("Job %s not found", job_id)
        raise
    except Exception as exc:
        retries = self.request.retries
        retry_count = retries + 1
        max_retries = self.max_retries

        if retries >= max_retries:
            store.update_job(
                job_uuid,
                status=JobStatus.FAILED,
                error=str(exc),
                retry_count=retry_count,
            )
            raise

        store.update_job(
            job_uuid,
            status=JobStatus.RETRYING,
            error=str(exc),
            retry_count=retry_count,
        )
        try:
            raise self.retry(
                exc=exc,
                countdown=_retry_countdown(retries),
                max_retries=max_retries,
            )
        except MaxRetriesExceededError:
            store.update_job(
                job_uuid,
                status=JobStatus.FAILED,
                error=str(exc),
                retry_count=retry_count,
            )
            raise
