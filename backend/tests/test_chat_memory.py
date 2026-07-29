from pathlib import Path

from app.core.config import Settings
from app.domain.contracts import RagCitation
from app.services.chat_memory import ChatMemoryStore


def memory_settings(database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        datahub_gms_url="",
        datahub_gms_token=None,
        chat_memory_enabled=True,
        chat_memory_max_turns=2,
        chat_memory_context_chars=5000,
        chat_memory_ttl_hours=168,
    )


def test_memory_is_session_scoped_bounded_and_clearable() -> None:
    path = Path(__file__).with_name(".chat-memory-test.db")
    path.unlink(missing_ok=True)
    store = ChatMemoryStore(memory_settings(f"sqlite:///{path}"))

    store.record_turn("browser-session-1", True, "first question", "first answer")
    store.record_turn("browser-session-1", True, "second question", "second answer")
    status = store.record_turn("browser-session-1", True, "third question", "third answer")

    assert status.enabled
    assert status.message_count == 2
    assert store.context_for("browser-session-1", True) == [
        ("second question", "second answer"),
        ("third question", "third answer"),
    ]
    assert store.context_for("browser-session-2", True) == []
    assert store.clear("browser-session-1").message_count == 0
    path.unlink()


def test_disabled_memory_is_never_read_or_written() -> None:
    path = Path(__file__).with_name(".chat-memory-disabled-test.db")
    path.unlink(missing_ok=True)
    store = ChatMemoryStore(memory_settings(f"sqlite:///{path}"))
    status = store.record_turn("browser-session-1", False, "question", "answer")

    assert not status.enabled
    assert store.context_for("browser-session-1", False) == []
    path.unlink()


def test_memory_keeps_only_a_verified_active_asset_and_clears_it() -> None:
    path = Path(__file__).with_name(".chat-memory-active-asset-test.db")
    path.unlink(missing_ok=True)
    store = ChatMemoryStore(memory_settings(f"sqlite:///{path}"))
    asset = RagCitation(
        urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.orders,PROD)",
        label="orders", entity_type="DATASET", platform_urn="urn:li:dataPlatform:snowflake",
        source="datahub_mcp_live",
    )

    store.record_turn("browser-session-1", True, "What is the schema?", "Verified.", asset)

    assert store.active_asset_for("browser-session-1", True) == asset
    store.clear("browser-session-1")
    assert store.active_asset_for("browser-session-1", True) is None
    path.unlink()
