from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_bootstrap_readiness(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lineageguard-api",
        "environment": "test",
        "datahub": "not_configured",
        "llm_providers": "not_configured",
    }
