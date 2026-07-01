"""Job persistence and orchestration."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.schemas.job import CreateJobRequest
from app.services.task_dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)


class JobNotFoundError(Exception):
    """Raised when a job id does not exist."""

    def __init__(self, job_id: UUID) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class JobEnqueueError(Exception):
    """Raised when a job record exists but cannot be queued."""

    def __init__(self, job_id: UUID, reason: str) -> None:
        self.job_id = job_id
        self.reason = reason
        super().__init__(f"Failed to enqueue job {job_id}: {reason}")


class JobService:
    """Create and retrieve background jobs."""

    def __init__(self, session: AsyncSession, task_dispatcher: TaskDispatcher) -> None:
        self._session = session
        self._task_dispatcher = task_dispatcher

    async def create_job(self, request: CreateJobRequest) -> Job:
        """Persist a pending job and enqueue it for worker execution."""
        job = Job(
            task_type=request.task_type.value,
            status=JobStatus.PENDING.value,
            payload=request.payload,
        )
        self._session.add(job)
        await self._session.flush()

        try:
            celery_task_id = self._task_dispatcher.enqueue(job)
        except Exception as exc:
            job.status = JobStatus.FAILED.value
            job.error = f"Failed to enqueue job: {exc}"
            await self._session.commit()
            logger.exception("Failed to enqueue job %s", job.id)
            raise JobEnqueueError(job.id, str(exc)) from exc

        job.celery_task_id = celery_task_id
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def get_job(self, job_id: UUID) -> Job:
        """Return a job by primary key or raise JobNotFoundError."""
        result = await self._session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise JobNotFoundError(job_id)
        return job
