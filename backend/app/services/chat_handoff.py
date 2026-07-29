"""Short-lived, server-owned handoffs from verified chat targets to analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from app.domain.contracts import RagCitation


class ChatHandoffError(ValueError):
    """A handoff is missing, expired, belongs to another session, or was altered."""


@dataclass(frozen=True)
class ChatHandoff:
    handoff_id: str
    session_id: str
    target: RagCitation
    expires_at: datetime


class ChatHandoffStore:
    """Bounded in-memory authority for read-only chat-to-analysis transitions."""

    def __init__(self, *, ttl_minutes: int = 15, max_entries: int = 500) -> None:
        self._ttl = timedelta(minutes=max(1, ttl_minutes))
        self._max_entries = max(10, max_entries)
        self._entries: dict[str, ChatHandoff] = {}
        self._lock = RLock()

    def issue(self, session_id: str | None, target: RagCitation) -> ChatHandoff | None:
        if not session_id:
            return None
        now = datetime.now(UTC)
        handoff = ChatHandoff(
            handoff_id=uuid4().hex,
            session_id=session_id,
            target=target,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._purge(now)
            self._clear_session_locked(session_id)
            if len(self._entries) >= self._max_entries:
                oldest = min(
                    self._entries.values(), key=lambda entry: entry.expires_at
                )
                self._entries.pop(oldest.handoff_id, None)
            self._entries[handoff.handoff_id] = handoff
        return handoff

    def authorize(
        self, handoff_id: str, session_id: str, requested_asset_urn: str
    ) -> ChatHandoff:
        now = datetime.now(UTC)
        with self._lock:
            self._purge(now)
            handoff = self._entries.get(handoff_id)
        if handoff is None:
            raise ChatHandoffError(
                "The verified chat handoff is missing or expired; resolve the asset again"
            )
        if handoff.session_id != session_id:
            raise ChatHandoffError(
                "The verified chat handoff belongs to another browser session"
            )
        if handoff.target.urn != requested_asset_urn:
            raise ChatHandoffError(
                "The analysis asset does not match the MCP-verified chat target"
            )
        return handoff

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def clear_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._clear_session_locked(session_id)

    def _clear_session_locked(self, session_id: str) -> None:
        session_entries = [
            key
            for key, entry in self._entries.items()
            if entry.session_id == session_id
        ]
        for key in session_entries:
            self._entries.pop(key, None)

    def _purge(self, now: datetime) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)


chat_handoff_store = ChatHandoffStore()
