"""Job persistence and orchestration."""

import logging
import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus, TaskType
from app.schemas.job import CreateJobRequest
from app.services.task_dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


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


@dataclass(frozen=True)
class JobCreateResult:
    """Outcome of a job creation request."""

    job: Job
    created: bool


@dataclass(frozen=True)
class JobListResult:
    """Paginated job query result."""

    items: list[Job]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.total == 0:
            return 0
        return math.ceil(self.total / self.page_size)


class JobService:
    """Create and retrieve background jobs."""

    def __init__(self, session: AsyncSession, task_dispatcher: TaskDispatcher) -> None:
        self._session = session
        self._task_dispatcher = task_dispatcher

    async def create_job(
        self,
        request: CreateJobRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobCreateResult:
        """Persist a pending job and enqueue it, or return an existing idempotent job."""
        if idempotency_key is not None:
            existing = await self.get_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                logger.info(
                    "Returning existing job %s for idempotency key %s",
                    existing.id,
                    idempotency_key,
                )
                return JobCreateResult(job=existing, created=False)

        job = Job(
            idempotency_key=idempotency_key,
            task_type=request.task_type.value,
            status=JobStatus.PENDING.value,
            payload=request.payload,
        )
        self._session.add(job)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            if idempotency_key is None:
                raise
            existing = await self.get_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                return JobCreateResult(job=existing, created=False)
            raise

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
        return JobCreateResult(job=job, created=True)

    async def get_job(self, job_id: UUID) -> Job:
        """Return a job by primary key or raise JobNotFoundError."""
        result = await self._session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        """Return a job by idempotency key, if one exists."""
        result = await self._session.execute(
            select(Job).where(Job.idempotency_key == idempotency_key),
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        task_type: TaskType | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> JobListResult:
        """Return a paginated list of jobs with optional filters."""
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        page = max(page, 1)

        filters = []
        if status is not None:
            filters.append(Job.status == status.value)
        if task_type is not None:
            filters.append(Job.task_type == task_type.value)

        count_stmt = select(func.count()).select_from(Job)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = select(Job)
        if filters:
            list_stmt = list_stmt.where(*filters)
        list_stmt = (
            list_stmt.order_by(Job.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(list_stmt)
        items = list(result.scalars().all())

        return JobListResult(items=items, total=total, page=page, page_size=page_size)
