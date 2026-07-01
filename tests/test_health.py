"""Health endpoint and dependency connectivity tests."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


def test_health_returns_ok_when_dependencies_available(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert len(body["services"]) == 2

    services_by_name = {service["name"]: service for service in body["services"]}
    assert services_by_name["redis"]["status"] == "ok"
    assert services_by_name["database"]["status"] == "ok"


def test_health_reports_degraded_when_redis_unavailable(
    client: TestClient,
    mock_redis_client: MagicMock,
) -> None:
    mock_redis_client.check_connectivity = AsyncMock(
        return_value=("unavailable", "Connection refused"),
    )

    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "degraded"
    redis = next(service for service in body["services"] if service["name"] == "redis")
    assert redis["status"] == "unavailable"


def test_openapi_docs_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Celery Task Pipeline API"
    assert "/health" in schema["paths"]


def test_celery_app_importable() -> None:
    from app.core.celery_app import celery_app

    assert celery_app.main == "celery_task_pipeline"
    assert celery_app.conf.task_serializer == "json"
