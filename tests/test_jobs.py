"""Job submission and retrieval tests."""

import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.models.job import JobStatus, TaskType
from app.services.task_dispatcher import TASK_NAME_BY_TYPE


def test_create_process_data_job_returns_201(
    client: TestClient,
    mock_task_dispatcher: MagicMock,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "process_data",
            "payload": {"input_text": "hello world", "delay_seconds": 1},
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "pending"
    assert body["task_type"] == "process_data"
    assert uuid.UUID(body["id"])
    assert body["created_at"]

    mock_task_dispatcher.enqueue.assert_called_once()
    enqueued_job = mock_task_dispatcher.enqueue.call_args.args[0]
    assert str(enqueued_job.id) == body["id"]
    assert enqueued_job.status == JobStatus.PENDING.value


def test_create_send_webhook_job_returns_201(
    client: TestClient,
    mock_task_dispatcher: MagicMock,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "send_webhook",
            "payload": {
                "url": "https://example.com/hook",
                "body": {"event": "done"},
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["task_type"] == "send_webhook"
    mock_task_dispatcher.enqueue.assert_called_once()


def test_create_job_persists_pending_status(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "process_data",
            "payload": {"input_text": "persist me"},
        },
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    get_response = client.get(f"/api/v1/jobs/{job_id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "pending"
    assert body["payload"] == {"input_text": "persist me", "delay_seconds": 0}
    assert body["celery_task_id"] == "mock-celery-task-id"


def test_get_job_returns_full_detail(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "process_data",
            "payload": {"input_text": "detail check"},
        },
    )
    job_id = create_response.json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "pending"
    assert body["task_type"] == "process_data"
    assert body["payload"] == {"input_text": "detail check", "delay_seconds": 0}
    assert body["result"] is None
    assert body["error"] is None
    assert body["retry_count"] == 0
    assert body["celery_task_id"] == "mock-celery-task-id"
    assert body["created_at"]
    assert body["updated_at"]


def test_get_job_not_found_returns_404(client: TestClient) -> None:
    missing_id = uuid.uuid4()
    response = client.get(f"/api/v1/jobs/{missing_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == f"Job not found: {missing_id}"


def test_create_job_invalid_payload_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "process_data",
            "payload": {"delay_seconds": 1},
        },
    )
    assert response.status_code == 422


def test_create_job_delay_seconds_above_cap_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            "task_type": "process_data",
            "payload": {"input_text": "slow", "delay_seconds": 31},
        },
    )
    assert response.status_code == 422


def test_task_dispatcher_maps_known_task_types() -> None:
    assert TASK_NAME_BY_TYPE[TaskType.PROCESS_DATA].endswith("process_data_task")
    assert TASK_NAME_BY_TYPE[TaskType.SEND_WEBHOOK].endswith("send_webhook_task")


def test_idempotency_key_returns_existing_job_without_duplicate_enqueue(
    client: TestClient,
    mock_task_dispatcher: MagicMock,
) -> None:
    headers = {"Idempotency-Key": "idem-key-001"}
    payload = {
        "task_type": "process_data",
        "payload": {"input_text": "once only"},
    }

    first = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    mock_task_dispatcher.enqueue.assert_called_once()


def test_idempotency_key_persisted_on_job(client: TestClient) -> None:
    headers = {"Idempotency-Key": "stored-key"}
    create = client.post(
        "/api/v1/jobs",
        json={"task_type": "process_data", "payload": {"input_text": "keyed"}},
        headers=headers,
    )
    job_id = create.json()["id"]

    detail = client.get(f"/api/v1/jobs/{job_id}")
    assert detail.json()["idempotency_key"] == "stored-key"


def test_empty_idempotency_key_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={"task_type": "process_data", "payload": {"input_text": "x"}},
        headers={"Idempotency-Key": "   "},
    )
    assert response.status_code == 422


def test_idempotency_key_too_long_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={"task_type": "process_data", "payload": {"input_text": "x"}},
        headers={"Idempotency-Key": "x" * 65},
    )
    assert response.status_code == 422


def test_list_jobs_returns_paginated_results(client: TestClient) -> None:
    for index in range(3):
        client.post(
            "/api/v1/jobs",
            json={
                "task_type": "process_data",
                "payload": {"input_text": f"job-{index}"},
            },
        )

    response = client.get("/api/v1/jobs", params={"page": 1, "page_size": 2})
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 2


def test_list_jobs_filters_by_status(client: TestClient) -> None:
    create = client.post(
        "/api/v1/jobs",
        json={"task_type": "process_data", "payload": {"input_text": "filter me"}},
    )
    job_id = create.json()["id"]

    response = client.get("/api/v1/jobs", params={"status": "pending"})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert job_id in ids

    empty = client.get("/api/v1/jobs", params={"status": "succeeded"})
    assert empty.json()["total"] == 0


def test_list_jobs_filters_by_task_type(client: TestClient) -> None:
    client.post(
        "/api/v1/jobs",
        json={
            "task_type": "send_webhook",
            "payload": {"url": "https://example.com/hook", "body": {}},
        },
    )
    client.post(
        "/api/v1/jobs",
        json={"task_type": "process_data", "payload": {"input_text": "data"}},
    )

    response = client.get("/api/v1/jobs", params={"task_type": "send_webhook"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["task_type"] == "send_webhook"
