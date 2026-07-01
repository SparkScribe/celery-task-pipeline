"""send_webhook Celery task implementation."""

import logging
import uuid
from typing import Any

import httpx
from celery import Task

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.models.job import JobStatus
from app.services.job_store import JobNotFoundError, JobStore
from app.tasks.retry import fail_or_retry_task

logger = logging.getLogger(__name__)

TASK_NAME = "app.tasks.send_webhook.send_webhook_task"


class SendWebhookError(Exception):
    """Raised when send_webhook input is invalid."""


class WebhookClientError(SendWebhookError):
    """Non-retryable webhook failure (4xx responses)."""


class WebhookRetryableError(Exception):
    """Retryable webhook failure (5xx responses or network errors)."""


def run_send_webhook(
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 10.0,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST the webhook body and return the HTTP status."""
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise SendWebhookError("payload.url is required")

    body = payload.get("body", {})
    if not isinstance(body, dict):
        raise SendWebhookError("payload.body must be an object")

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout_seconds)
    try:
        response = client.post(url, json=body)
        if response.status_code >= 500:
            raise WebhookRetryableError(f"Webhook returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise WebhookClientError(f"Webhook returned HTTP {response.status_code}")
        return {"http_status": response.status_code}
    except httpx.TimeoutException as exc:
        raise WebhookRetryableError(f"Webhook request timed out: {exc}") from exc
    except httpx.NetworkError as exc:
        raise WebhookRetryableError(f"Webhook network error: {exc}") from exc
    finally:
        if owns_client:
            client.close()


def execute_send_webhook(
    job_id: uuid.UUID,
    job_store: JobStore | None = None,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Load a job, mark it running, deliver the webhook, and persist the result."""
    store = job_store or JobStore()
    settings = get_settings()

    job = store.get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    store.update_job(job_id, status=JobStatus.RUNNING, clear_error=True)
    result = run_send_webhook(
        job.payload,
        timeout_seconds=settings.webhook_timeout_seconds,
        http_client=http_client,
    )
    store.update_job(job_id, status=JobStatus.SUCCEEDED, result=result, clear_error=True)
    return result


@celery_app.task(bind=True, name=TASK_NAME, max_retries=get_settings().celery_task_max_retries)
def send_webhook_task(self: Task, job_id: str) -> dict[str, Any]:
    """Celery entrypoint for the send_webhook job type."""
    store = JobStore()
    job_uuid = uuid.UUID(job_id)

    try:
        return execute_send_webhook(job_uuid, store)
    except JobNotFoundError:
        logger.error("Job %s not found", job_id)
        raise
    except WebhookClientError as exc:
        store.update_job(
            job_uuid,
            status=JobStatus.FAILED,
            error=str(exc),
            retry_count=self.request.retries,
        )
        raise
    except Exception as exc:
        fail_or_retry_task(self, job_uuid, store, exc)
