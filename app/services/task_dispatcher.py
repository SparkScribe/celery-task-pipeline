"""Dispatch accepted jobs to Celery workers."""

import logging

from celery import Celery

from app.models.job import Job, TaskType

logger = logging.getLogger(__name__)

TASK_NAME_BY_TYPE: dict[TaskType, str] = {
    TaskType.PROCESS_DATA: "app.tasks.process_data.process_data_task",
    TaskType.SEND_WEBHOOK: "app.tasks.send_webhook.send_webhook_task",
}


class TaskDispatcher:
    """Enqueue jobs on the Celery broker."""

    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    def enqueue(self, job: Job) -> str:
        """Send a job to the worker queue and return the Celery task id."""
        task_name = TASK_NAME_BY_TYPE[TaskType(job.task_type)]
        async_result = self._celery_app.send_task(
            task_name,
            kwargs={"job_id": str(job.id)},
        )
        logger.info(
            "Enqueued job %s as Celery task %s (%s)",
            job.id,
            async_result.id,
            task_name,
        )
        return async_result.id
