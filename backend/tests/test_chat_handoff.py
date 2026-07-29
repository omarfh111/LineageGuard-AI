from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.datahub.mcp_client import get_datahub_client
from app.domain.contracts import RagCitation
from app.main import app
from app.services.chat_handoff import ChatHandoffError, ChatHandoffStore
from app.services.chat_handoff import chat_handoff_store
from test_impact_analysis import (
    FakeDataHubMcpClient,
    SOURCE_URN,
    request_payload,
)


TARGET = RagCitation(
    urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
    label="orders",
    entity_type="DATASET",
    platform_urn="urn:li:dataPlatform:snowflake",
    source="datahub_mcp_live",
)


def test_handoff_authorizes_only_the_exact_session_and_asset() -> None:
    store = ChatHandoffStore()
    handoff = store.issue("browser-session-1", TARGET)
    assert handoff is not None

    authorized = store.authorize(
        handoff.handoff_id, "browser-session-1", TARGET.urn
    )

    assert authorized.target.urn == TARGET.urn
    with pytest.raises(ChatHandoffError, match="another browser session"):
        store.authorize(handoff.handoff_id, "browser-session-2", TARGET.urn)
    with pytest.raises(ChatHandoffError, match="does not match"):
        store.authorize(
            handoff.handoff_id,
            "browser-session-1",
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,customers,PROD)",
        )


def test_handoff_requires_a_session_and_expires_fail_closed() -> None:
    assert ChatHandoffStore().issue(None, TARGET) is None
    store = ChatHandoffStore(ttl_minutes=1)
    handoff = store.issue("browser-session-1", TARGET)
    assert handoff is not None
    store._entries[handoff.handoff_id] = handoff.__class__(
        handoff_id=handoff.handoff_id,
        session_id=handoff.session_id,
        target=handoff.target,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(ChatHandoffError, match="missing or expired"):
        store.authorize(handoff.handoff_id, "browser-session-1", TARGET.urn)


def test_handoff_store_is_bounded() -> None:
    store = ChatHandoffStore(max_entries=10)
    for index in range(20):
        issued = store.issue(f"browser-session-{index}", TARGET)
        assert issued is not None

    assert len(store._entries) == 10


def test_new_handoff_revokes_the_previous_target_for_the_session() -> None:
    store = ChatHandoffStore()
    first = store.issue("browser-session-1", TARGET)
    second = store.issue(
        "browser-session-1",
        TARGET.model_copy(
            update={
                "urn": (
                    "urn:li:dataset:"
                    "(urn:li:dataPlatform:snowflake,customers,PROD)"
                )
            }
        ),
    )
    assert first is not None and second is not None

    with pytest.raises(ChatHandoffError, match="missing or expired"):
        store.authorize(first.handoff_id, "browser-session-1", TARGET.urn)
    assert (
        store.authorize(
            second.handoff_id,
            "browser-session-1",
            second.target.urn,
        ).target.urn
        == second.target.urn
    )


def test_chat_analysis_rejects_asset_substitution() -> None:
    chat_handoff_store.clear()
    target = TARGET.model_copy(update={"urn": SOURCE_URN})
    handoff = chat_handoff_store.issue("browser-session-1", target)
    assert handoff is not None
    payload = request_payload()
    payload["asset_urn"] = (
        "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.customers,PROD)"
    )
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).post(
            "/api/v1/chat/execute-analysis",
            json={
                "change_request": payload,
                "confirmed": True,
                "handoff_id": handoff.handoff_id,
                "session_id": "browser-session-1",
            },
        )
    finally:
        app.dependency_overrides.clear()
        chat_handoff_store.clear()

    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_chat_analysis_accepts_the_exact_verified_handoff() -> None:
    chat_handoff_store.clear()
    target = TARGET.model_copy(update={"urn": SOURCE_URN})
    handoff = chat_handoff_store.issue("browser-session-1", target)
    assert handoff is not None
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).post(
            "/api/v1/chat/execute-analysis",
            json={
                "change_request": request_payload(),
                "confirmed": True,
                "handoff_id": handoff.handoff_id,
                "session_id": "browser-session-1",
            },
        )
    finally:
        app.dependency_overrides.clear()
        chat_handoff_store.clear()

    assert response.status_code == 200
    assert response.json()["impact_report"]["request"]["asset_urn"] == SOURCE_URN
