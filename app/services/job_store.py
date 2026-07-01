"""Synchronous job persistence used by Celery workers."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.sync_session import get_sync_session_factory
from app.models.job import Job, JobStatus, TaskType


class JobNotFoundError(Exception):
    """Raised when a job id does not exist."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class JobStore:
    """Read and update job rows from worker processes."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_sync_session_factory()

    def get_job(self, job_id: uuid.UUID) -> Job | None:
        with self._session_factory() as session:
            return session.get(Job, job_id)

    def create_job(
        self,
        *,
        task_type: TaskType,
        payload: dict[str, Any],
        status: JobStatus = JobStatus.PENDING,
        celery_task_id: str | None = None,
    ) -> Job:
        with self._session_factory() as session:
            job = Job(
                task_type=task_type.value,
                status=status.value,
                payload=payload,
                celery_task_id=celery_task_id,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def update_job(
        self,
        job_id: uuid.UUID,
        *,
        status: JobStatus | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        retry_count: int | None = None,
        clear_error: bool = False,
    ) -> Job:
        with self._session_factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFoundError(job_id)

            if status is not None:
                job.status = status.value
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            elif clear_error:
                job.error = None
            if retry_count is not None:
                job.retry_count = retry_count
            job.updated_at = datetime.now(UTC)

            session.commit()
            session.refresh(job)
            return job

    def list_jobs(self) -> list[Job]:
        with self._session_factory() as session:
            result = session.execute(select(Job).order_by(Job.created_at.desc()))
            return list(result.scalars().all())
