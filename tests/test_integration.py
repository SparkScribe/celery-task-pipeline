"""Integration tests that require a running API + worker stack.

Run locally after `docker compose up`, or rely on CI docker job:

    pytest tests -m integration -v
"""

import os
import time
import uuid

import httpx
import pytest

API_URL = os.getenv("API_URL", "http://localhost:8000")
INTEGRATION_TIMEOUT_SECONDS = float(os.getenv("INTEGRATION_TIMEOUT_SECONDS", "60"))


def _api_reachable() -> bool:
    try:
        response = httpx.get(f"{API_URL}/health", timeout=2.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def require_api() -> None:
    if not _api_reachable():
        pytest.skip(f"API not reachable at {API_URL} — start docker compose first")


@pytest.mark.usefixtures("require_api")
def test_live_process_data_job_reaches_succeeded() -> None:
    """Submit a job against a running stack and poll until succeeded."""
    with httpx.Client(base_url=API_URL, timeout=10.0) as client:
        create = client.post(
            "/api/v1/jobs",
            json={
                "task_type": "process_data",
                "payload": {"input_text": "integration test", "delay_seconds": 0},
            },
        )
        assert create.status_code == 201
        job_id = create.json()["id"]

        deadline = time.monotonic() + INTEGRATION_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            detail = client.get(f"/api/v1/jobs/{job_id}")
            assert detail.status_code == 200
            body = detail.json()
            if body["status"] == "succeeded":
                assert body["result"]["output_text"] == "INTEGRATION TEST"
                assert body["result"]["word_count"] == 2
                return
            if body["status"] == "failed":
                pytest.fail(f"Job failed: {body.get('error')}")
            time.sleep(2)

        pytest.fail(f"Job {job_id} did not succeed within {INTEGRATION_TIMEOUT_SECONDS}s")


@pytest.mark.usefixtures("require_api")
def test_live_idempotency_key_deduplicates_jobs() -> None:
    """Duplicate Idempotency-Key returns 200 without creating a second job."""
    key = f"integration-{uuid.uuid4()}"
    headers = {"Idempotency-Key": key}
    payload = {
        "task_type": "process_data",
        "payload": {"input_text": "dedupe", "delay_seconds": 0},
    }

    with httpx.Client(base_url=API_URL, timeout=10.0) as client:
        first = client.post("/api/v1/jobs", json=payload, headers=headers)
        second = client.post("/api/v1/jobs", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
