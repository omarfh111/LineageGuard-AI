from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_runtime_configuration_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://localhost:8080")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DEMO_MODE", "true")
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lineageguard-api",
        "environment": "test",
        "datahub": "configured",
        "llm_providers": "partial",
        "qdrant": "configured",
        "demo_mode": True,
    }
