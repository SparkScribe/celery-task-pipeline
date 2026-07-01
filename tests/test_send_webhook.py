"""Unit tests for the send_webhook task logic and worker execution."""

import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.db.base import Base
from app.db.sync_session import reset_sync_session_factory
from app.models.job import JobStatus, TaskType
from app.services.job_store import JobNotFoundError, JobStore
from app.tasks.send_webhook import (
    SendWebhookError,
    WebhookClientError,
    WebhookRetryableError,
    execute_send_webhook,
    run_send_webhook,
    send_webhook_task,
)


@pytest.fixture
def sync_job_store(tmp_path, monkeypatch):
    """SQLite-backed JobStore for worker task tests."""
    reset_sync_session_factory()
    get_settings.cache_clear()

    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    store = JobStore(sessionmaker(bind=engine, autoflush=False, autocommit=False))

    yield store

    engine.dispose()
    reset_sync_session_factory()
    get_settings.cache_clear()


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://example.com/hook")
    return httpx.Response(status_code, request=request)


def test_run_send_webhook_posts_json_and_returns_status() -> None:
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = _http_response(202)

    result = run_send_webhook(
        {"url": "https://example.com/hook", "body": {"event": "done"}},
        http_client=client,
    )

    assert result == {"http_status": 202}
    client.post.assert_called_once_with(
        "https://example.com/hook",
        json={"event": "done"},
    )


def test_run_send_webhook_retries_on_5xx() -> None:
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = _http_response(503)

    with pytest.raises(WebhookRetryableError, match="503"):
        run_send_webhook(
            {"url": "https://example.com/hook", "body": {}},
            http_client=client,
        )


def test_run_send_webhook_fails_on_4xx_without_retry() -> None:
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = _http_response(404)

    with pytest.raises(WebhookClientError, match="404"):
        run_send_webhook(
            {"url": "https://example.com/hook", "body": {}},
            http_client=client,
        )


def test_run_send_webhook_retries_on_network_error() -> None:
    client = MagicMock(spec=httpx.Client)
    request = httpx.Request("POST", "https://example.com/hook")
    client.post.side_effect = httpx.ConnectError("connection refused", request=request)

    with pytest.raises(WebhookRetryableError, match="network error"):
        run_send_webhook(
            {"url": "https://example.com/hook", "body": {}},
            http_client=client,
        )


def test_run_send_webhook_retries_on_timeout() -> None:
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = httpx.TimeoutException("timed out")

    with pytest.raises(WebhookRetryableError, match="timed out"):
        run_send_webhook(
            {"url": "https://example.com/hook", "body": {}},
            http_client=client,
        )


def test_run_send_webhook_requires_url() -> None:
    with pytest.raises(SendWebhookError, match="url"):
        run_send_webhook({"body": {}}, http_client=MagicMock(spec=httpx.Client))


def test_execute_send_webhook_updates_job_lifecycle(sync_job_store: JobStore) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.SEND_WEBHOOK,
        payload={"url": "https://example.com/hook", "body": {"event": "done"}},
    )
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = _http_response(200)

    result = execute_send_webhook(job.id, sync_job_store, http_client=client)

    assert result == {"http_status": 200}
    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.SUCCEEDED.value
    assert updated.result == {"http_status": 200}


def test_execute_send_webhook_raises_when_job_missing(sync_job_store: JobStore) -> None:
    with pytest.raises(JobNotFoundError):
        execute_send_webhook(uuid.uuid4(), sync_job_store, http_client=MagicMock(spec=httpx.Client))


@patch("app.tasks.send_webhook.execute_send_webhook")
def test_send_webhook_task_run_invokes_executor(mock_execute) -> None:
    job_id = uuid.uuid4()
    mock_execute.return_value = {"http_status": 204}

    result = send_webhook_task.run(job_id=str(job_id))

    assert result == {"http_status": 204}
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[0] == job_id


def test_send_webhook_task_marks_job_failed_on_client_error(
    sync_job_store: JobStore,
    monkeypatch,
) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.SEND_WEBHOOK,
        payload={"url": "https://example.com/hook", "body": {}},
    )

    def raise_client_error(*_args, **_kwargs):
        raise WebhookClientError("Webhook returned HTTP 400")

    monkeypatch.setattr("app.tasks.send_webhook.run_send_webhook", raise_client_error)

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        with pytest.raises(WebhookClientError):
            send_webhook_task.apply(kwargs={"job_id": str(job.id)})
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False

    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.FAILED.value
    assert "400" in (updated.error or "")


def test_send_webhook_task_marks_job_retrying_on_retryable_error(
    sync_job_store: JobStore,
    monkeypatch,
) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.SEND_WEBHOOK,
        payload={"url": "https://example.com/hook", "body": {}},
    )

    def raise_retryable(*_args, **_kwargs):
        raise WebhookRetryableError("Webhook returned HTTP 503")

    monkeypatch.setattr("app.tasks.send_webhook.run_send_webhook", raise_retryable)

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        with pytest.raises(Retry):
            send_webhook_task.apply(kwargs={"job_id": str(job.id)})
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False

    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.RETRYING.value
    assert updated.retry_count == 1


def test_send_webhook_task_eager_updates_job(sync_job_store: JobStore, monkeypatch) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.SEND_WEBHOOK,
        payload={"url": "https://example.com/hook", "body": {"ok": True}},
    )
    monkeypatch.setattr(
        "app.tasks.send_webhook.run_send_webhook",
        lambda payload, **kwargs: {"http_status": 201},
    )

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        send_webhook_task.apply(kwargs={"job_id": str(job.id)})
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False

    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.SUCCEEDED.value
    assert updated.result == {"http_status": 201}
