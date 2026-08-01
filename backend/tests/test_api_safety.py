import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_local_memory_delete_preflight() -> None:
    response = TestClient(app).options(
        "/api/v1/chat/memory/browser-session-123",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_allows_reviewer_capability_header_only_from_local_ui() -> None:
    client = TestClient(app)
    accepted = client.options(
        "/api/v1/writebacks/prepare",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-lineageguard-reviewer-capability",
        },
    )
    rejected = client.options(
        "/api/v1/writebacks/prepare",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-lineageguard-reviewer-capability",
        },
    )

    assert accepted.status_code == 200
    assert "x-lineageguard-reviewer-capability" in accepted.headers["access-control-allow-headers"].lower()
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_write_route_fails_cleanly_when_writeback_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DATAHUB_WRITEBACK_ENABLED", "false")
    monkeypatch.setenv("LOCAL_REVIEWER_CAPABILITY", "a" * 32)

    response = TestClient(app).post(
        "/api/v1/writebacks/prepare",
        headers={"X-LineageGuard-Reviewer-Capability": "a" * 32},
        json={"run_id": "missing-run", "idempotency_key": "safe-test-key"},
    )

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/writebacks/missing-run/approve", {"decision": "APPROVE_REPORT", "comment": "reviewed", "idempotency_key": "safe-test-key"}),
        ("/api/v1/writebacks/missing-run/rollback", {"decision": "APPROVE_ROLLBACK", "comment": "reviewed", "idempotency_key": "safe-test-key"}),
        ("/api/v1/writebacks/missing-run/reconcile", {"action": "CONFIRM_NO_DOCUMENT_CREATED", "comment": "reviewed", "idempotency_key": "safe-test-key"}),
    ],
)
def test_every_write_transition_stops_before_state_change_when_disabled(
    monkeypatch, path: str, payload: dict[str, str]
) -> None:
    monkeypatch.setenv("DATAHUB_WRITEBACK_ENABLED", "false")
    monkeypatch.setenv("LOCAL_REVIEWER_CAPABILITY", "a" * 32)

    response = TestClient(app).post(
        path,
        headers={"X-LineageGuard-Reviewer-Capability": "a" * 32},
        json=payload,
    )

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


def test_write_route_requires_configured_strong_reviewer_capability(monkeypatch) -> None:
    monkeypatch.setenv("DATAHUB_WRITEBACK_ENABLED", "true")
    monkeypatch.delenv("LOCAL_REVIEWER_CAPABILITY", raising=False)
    client = TestClient(app)

    unconfigured = client.post(
        "/api/v1/writebacks/prepare",
        json={"run_id": "missing-run", "idempotency_key": "safe-test-key"},
    )
    monkeypatch.setenv("LOCAL_REVIEWER_CAPABILITY", "b" * 32)
    missing = client.post(
        "/api/v1/writebacks/prepare",
        json={"run_id": "missing-run", "idempotency_key": "safe-test-key"},
    )
    wrong = client.post(
        "/api/v1/writebacks/prepare",
        headers={"X-LineageGuard-Reviewer-Capability": "c" * 32},
        json={"run_id": "missing-run", "idempotency_key": "safe-test-key"},
    )
    authorized = client.post(
        "/api/v1/writebacks/prepare",
        headers={"X-LineageGuard-Reviewer-Capability": "b" * 32},
        json={"run_id": "missing-run", "idempotency_key": "safe-test-key"},
    )

    assert unconfigured.status_code == 503
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert authorized.status_code == 404
