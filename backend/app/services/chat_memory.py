"""Bounded, user-clearable conversation memory for the read-only DataHub chat.

The store deliberately retains only a session identifier plus the user's question
and the safe final answer. It never stores API keys, raw MCP payloads, chain of
thought, DataHub write credentials, or confirmation authority. Earlier turns are
context only: every factual answer still requires fresh MCP verification.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings, get_settings
from app.domain.contracts import ChatMemoryStatus, RagCitation
from app.services.run_store import sqlite_path


class ChatMemoryStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._path = sqlite_path(self._settings.database_url)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_memory_session ON chat_memory_turns(session_id, id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory_active_assets (
                    session_id TEXT PRIMARY KEY,
                    urn TEXT NOT NULL,
                    label TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    platform_urn TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def context_for(self, session_id: str | None, enabled: bool) -> list[tuple[str, str]]:
        """Return recent turns oldest-first, bounded in count and total size."""

        if not enabled or not session_id or not self._settings.chat_memory_enabled:
            return []
        self._purge_expired()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT user_message, assistant_answer
                FROM (
                    SELECT user_message, assistant_answer, id
                    FROM chat_memory_turns
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (session_id, self._settings.chat_memory_max_turns),
            ).fetchall()
        remaining = self._settings.chat_memory_context_chars
        turns: list[tuple[str, str]] = []
        for row in rows:
            question = str(row["user_message"])
            answer = str(row["assistant_answer"])
            size = len(question) + len(answer)
            if size > remaining and turns:
                continue
            turns.append((question[:2000], answer[:4000]))
            remaining -= size
        return turns

    def record_turn(
        self, session_id: str | None, enabled: bool, question: str, answer: str,
        active_asset: RagCitation | None = None,
    ) -> ChatMemoryStatus:
        if not enabled or not session_id or not self._settings.chat_memory_enabled:
            return ChatMemoryStatus(session_id=session_id, enabled=False, max_turns=self._settings.chat_memory_max_turns)
        now = datetime.now(UTC)
        self._purge_expired(now)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO chat_memory_turns(session_id, user_message, assistant_answer, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, question[:4000], answer[:6000], now.isoformat()),
            )
            connection.execute(
                """
                DELETE FROM chat_memory_turns
                WHERE session_id = ? AND id NOT IN (
                    SELECT id FROM chat_memory_turns
                    WHERE session_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (session_id, session_id, self._settings.chat_memory_max_turns),
            )
            if active_asset:
                connection.execute(
                    """
                    INSERT INTO chat_memory_active_assets(session_id, urn, label, entity_type, platform_urn, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET urn=excluded.urn, label=excluded.label,
                    entity_type=excluded.entity_type, platform_urn=excluded.platform_urn, updated_at=excluded.updated_at
                    """,
                    (session_id, active_asset.urn, active_asset.label, active_asset.entity_type, active_asset.platform_urn, now.isoformat()),
                )
            else:
                connection.execute("DELETE FROM chat_memory_active_assets WHERE session_id = ?", (session_id,))
        return self.status(session_id, enabled=True)

    def active_asset_for(self, session_id: str | None, enabled: bool) -> RagCitation | None:
        """Return only the last unambiguous asset that completed MCP verification."""

        if not enabled or not session_id or not self._settings.chat_memory_enabled:
            return None
        self._purge_expired()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT urn, label, entity_type, platform_urn FROM chat_memory_active_assets WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return RagCitation(
            urn=str(row["urn"]), label=str(row["label"]), entity_type=str(row["entity_type"]),
            platform_urn=str(row["platform_urn"]) if row["platform_urn"] else None,
            source="datahub_mcp_live",
        )

    def status(self, session_id: str | None, enabled: bool = True) -> ChatMemoryStatus:
        if not enabled or not session_id or not self._settings.chat_memory_enabled:
            return ChatMemoryStatus(session_id=session_id, enabled=False, max_turns=self._settings.chat_memory_max_turns)
        self._purge_expired()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MAX(created_at) AS last_updated_at "
                "FROM chat_memory_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return ChatMemoryStatus(
            session_id=session_id,
            enabled=True,
            message_count=int(row["count"]),
            max_turns=self._settings.chat_memory_max_turns,
            last_updated_at=datetime.fromisoformat(row["last_updated_at"]) if row["last_updated_at"] else None,
        )

    def clear(self, session_id: str) -> ChatMemoryStatus:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM chat_memory_turns WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM chat_memory_active_assets WHERE session_id = ?", (session_id,))
        return ChatMemoryStatus(
            session_id=session_id,
            enabled=self._settings.chat_memory_enabled,
            max_turns=self._settings.chat_memory_max_turns,
        )

    def _purge_expired(self, now: datetime | None = None) -> None:
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=self._settings.chat_memory_ttl_hours)
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM chat_memory_turns WHERE created_at < ?", (cutoff.isoformat(),))


chat_memory_store = ChatMemoryStore()
