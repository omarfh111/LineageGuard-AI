from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_runtime_configuration_without_secrets(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY", "OPENAI_JUDGE_MODEL", "OPENAI_CHAT_MODEL",
        "GROQ_API_KEY", "GROQ_JUDGE_MODEL",
        "NVIDIA_API_KEY", "NVIDIA_CRITIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
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
        "writeback": "disabled",
        "demo_mode": True,
        "providers": {
            "chat": {
                "available": True,
                "model": "deterministic-demo-fallback",
                "mode": "local_fallback",
                "reason": "Using the deterministic local demonstration fallback.",
            },
            "nvidia_critic": {
                "available": False,
                "model": None,
                "mode": "external",
                "reason": "NVIDIA critic credentials and model are not configured.",
            },
            "openai_judge": {
                "available": False,
                "model": None,
                "mode": "external",
                "reason": "OpenAI judge model are not configured.",
            },
            "groq_judge": {
                "available": False,
                "model": None,
                "mode": "external",
                "reason": "Groq judge credentials and model are not configured.",
            },
        },
    }


def test_health_requires_both_credentials_and_model_for_provider_buttons(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY", "OPENAI_JUDGE_MODEL", "OPENAI_CHAT_MODEL",
        "GROQ_API_KEY", "GROQ_JUDGE_MODEL",
        "NVIDIA_API_KEY", "NVIDIA_CRITIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_JUDGE_MODEL", "gpt-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia")
    monkeypatch.delenv("NVIDIA_CRITIC_MODEL", raising=False)
    monkeypatch.setenv("GROQ_JUDGE_MODEL", "groq-test")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    payload = TestClient(app).get("/api/v1/health").json()

    assert payload["providers"]["openai_judge"]["available"] is True
    assert payload["providers"]["nvidia_critic"]["available"] is False
    assert payload["providers"]["groq_judge"]["available"] is False
    assert payload["llm_providers"] == "partial"
