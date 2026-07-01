"""Unit tests for the process_data task logic and worker execution."""

import uuid
from unittest.mock import patch

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
from app.tasks.process_data import (
    ProcessDataError,
    execute_process_data,
    process_data_task,
    run_process_data,
)


@pytest.fixture
def sync_job_store(tmp_path, monkeypatch):
    """SQLite-backed JobStore shared between async API URL config and sync workers."""
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


def test_run_process_data_transforms_text() -> None:
    result = run_process_data({"input_text": "hello world", "delay_seconds": 0})
    assert result == {"output_text": "HELLO WORLD", "word_count": 2}


def test_run_process_data_caps_delay(monkeypatch) -> None:
    slept: list[int] = []

    def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.tasks.process_data.time.sleep", fake_sleep)
    run_process_data({"input_text": "hi", "delay_seconds": 99}, max_delay_seconds=30)
    assert slept == [30]


@patch("app.tasks.process_data.time.sleep")
def test_run_process_data_skips_sleep_when_zero(mock_sleep) -> None:
    run_process_data({"input_text": "hi", "delay_seconds": 0})
    mock_sleep.assert_not_called()


def test_run_process_data_requires_input_text() -> None:
    with pytest.raises(ProcessDataError, match="input_text"):
        run_process_data({"delay_seconds": 0})


def test_execute_process_data_updates_job_lifecycle(sync_job_store: JobStore) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.PROCESS_DATA,
        payload={"input_text": "async workers", "delay_seconds": 0},
    )

    result = execute_process_data(job.id, sync_job_store)

    assert result == {"output_text": "ASYNC WORKERS", "word_count": 2}
    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.SUCCEEDED.value
    assert updated.result == result
    assert updated.error is None


def test_execute_process_data_raises_when_job_missing(sync_job_store: JobStore) -> None:
    with pytest.raises(JobNotFoundError):
        execute_process_data(uuid.uuid4(), sync_job_store)


@patch("app.tasks.process_data.execute_process_data")
def test_process_data_task_run_invokes_executor(mock_execute) -> None:
    job_id = uuid.uuid4()
    mock_execute.return_value = {"output_text": "OK", "word_count": 1}

    result = process_data_task.run(job_id=str(job_id))

    assert result == {"output_text": "OK", "word_count": 1}
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[0] == job_id


def test_process_data_task_marks_job_retrying_on_failure(
    sync_job_store: JobStore,
    monkeypatch,
) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.PROCESS_DATA,
        payload={"input_text": "fail me", "delay_seconds": 0},
    )

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.tasks.process_data.run_process_data", raise_error)

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        with pytest.raises(Retry):
            process_data_task.apply(kwargs={"job_id": str(job.id)})
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False

    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.RETRYING.value
    assert updated.error == "boom"
    assert updated.retry_count == 1


def test_process_data_task_eager_updates_job(sync_job_store: JobStore) -> None:
    job = sync_job_store.create_job(
        task_type=TaskType.PROCESS_DATA,
        payload={"input_text": "hello world", "delay_seconds": 0},
    )

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        process_data_task.apply(kwargs={"job_id": str(job.id)})
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False

    updated = sync_job_store.get_job(job.id)
    assert updated is not None
    assert updated.status == JobStatus.SUCCEEDED.value
    assert updated.result == {"output_text": "HELLO WORLD", "word_count": 2}
