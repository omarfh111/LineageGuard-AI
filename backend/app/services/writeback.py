"""Approval-gated, persistent document write-back with scoped compensation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import (
    ApprovalRequest,
    AuditEvent,
    HumanDecision,
    WritebackPreparationRequest,
    WritebackProposal,
    WritebackStatus,
)
from app.services.run_store import sqlite_path


class DocumentWriter(Protocol):
    async def save(self, title: str, content: str, related_asset: str) -> str: ...

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None: ...


class WritebackError(ValueError):
    pass


class McpDocumentWriter:
    def __init__(self, client: DataHubMcpClient) -> None:
        self.client = client

    async def save(self, title: str, content: str, related_asset: str) -> str:
        result = await self.client.save_document(title, content, related_asset)
        match = re.search(r"urn:li:document:[A-Za-z0-9._-]+", json.dumps(result))
        if not match:
            raise WritebackError("DataHub did not return a document URN")
        return match.group(0)

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None:
        await self.client.save_document(
            "Superseded LineageGuard analysis", content, related_asset, urn=document_urn
        )


class WritebackRepository:
    """SQLite audit trail. SQLite is sufficient for the single-process MVP."""

    def __init__(self, database_url: str | None = None) -> None:
        self._path = sqlite_path(database_url or get_settings().database_url)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writeback_proposals (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    report_hash TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    UNIQUE(idempotency_key, report_hash)
                );
                CREATE TABLE IF NOT EXISTS writeback_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                """
            )

    def save(self, proposal: WritebackProposal) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO writeback_proposals(run_id, idempotency_key, report_hash, proposal_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET proposal_json = excluded.proposal_json
                """,
                (
                    proposal.run_id,
                    proposal.idempotency_key,
                    proposal.report_hash,
                    proposal.model_dump_json(),
                ),
            )

    def get(self, run_id: str) -> WritebackProposal | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT proposal_json FROM writeback_proposals WHERE run_id = ?", (run_id,)
            ).fetchone()
        return WritebackProposal.model_validate_json(row["proposal_json"]) if row else None

    def find_by_idempotency(
        self, idempotency_key: str, report_hash: str
    ) -> WritebackProposal | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT proposal_json FROM writeback_proposals
                WHERE idempotency_key = ? AND report_hash = ?
                """,
                (idempotency_key, report_hash),
            ).fetchone()
        return WritebackProposal.model_validate_json(row["proposal_json"]) if row else None

    def add_event(self, event: AuditEvent) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO writeback_audit_events(run_id, event_json) VALUES (?, ?)",
                (event.run_id, event.model_dump_json()),
            )

    def events(self, run_id: str) -> list[AuditEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT event_json FROM writeback_audit_events WHERE run_id = ? ORDER BY event_id",
                (run_id,),
            ).fetchall()
        return [AuditEvent.model_validate_json(row["event_json"]) for row in rows]


class WritebackService:
    def __init__(
        self, writer: DocumentWriter, repository: WritebackRepository | None = None
    ) -> None:
        self.writer = writer
        self.repository = repository or WritebackRepository("sqlite:///:memory:")

    def prepare(self, request: WritebackPreparationRequest) -> WritebackProposal:
        result = request.judging_result
        if not result.deterministic_validation.passed:
            raise WritebackError("Gate 0 must pass before write-back preparation")
        if (
            not result.aggregate_decision
            or result.aggregate_decision.decision != "FINALIZE_READ_ONLY"
        ):
            raise WritebackError("Double PASS is required before write-back preparation")

        report = request.judging_request.impact_report
        payload = report.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.repository.find_by_idempotency(request.idempotency_key, digest)
        if existing:
            return existing

        proposal = WritebackProposal(
            run_id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            report_hash=digest,
            target_asset_urn=report.request.asset_urn,
            document_title=f"LineageGuard analysis {digest[:12]}",
            document_content=payload,
            snapshot={"document_urn": None, "exists": False, "pre_write_document": None},
        )
        self.repository.save(proposal)
        self._audit(proposal.run_id, "WRITEBACK_PREPARED", {"report_hash": digest})
        return proposal

    async def decide(self, run_id: str, approval: ApprovalRequest) -> WritebackProposal:
        proposal = self._authorized_proposal(run_id, approval.idempotency_key)
        if proposal.status is WritebackStatus.COMPLETED:
            return proposal
        if proposal.status is WritebackStatus.REJECTED:
            if approval.decision is HumanDecision.REJECT:
                return proposal
            raise WritebackError("A rejected proposal cannot be approved")
        if approval.decision is HumanDecision.REJECT:
            proposal.status = WritebackStatus.REJECTED
            self.repository.save(proposal)
            self._audit(run_id, "REJECTED", {"comment": approval.comment})
            return proposal
        if approval.decision is not HumanDecision.APPROVE_REPORT:
            raise WritebackError("Only APPROVE_REPORT may execute this write-back")

        proposal.status = WritebackStatus.APPROVED
        self.repository.save(proposal)
        self._audit(run_id, "APPROVED", {"comment": approval.comment})
        proposal.status = WritebackStatus.WRITEBACK_PENDING
        self.repository.save(proposal)
        self._audit(run_id, "WRITEBACK_PENDING", {})
        try:
            document_urn = await self.writer.save(
                proposal.document_title,
                proposal.document_content,
                proposal.target_asset_urn,
            )
        except Exception:
            proposal.status = WritebackStatus.FAILED
            self.repository.save(proposal)
            self._audit(run_id, "WRITEBACK_FAILED", {})
            raise

        proposal.snapshot = {
            "document_urn": document_urn,
            "exists": True,
            "pre_write_document": None,
        }
        proposal.status = WritebackStatus.COMPLETED
        self.repository.save(proposal)
        self._audit(run_id, "WRITEBACK_COMPLETED", {"document_urn": document_urn})
        return proposal

    async def rollback(self, run_id: str, approval: ApprovalRequest) -> WritebackProposal:
        proposal = self._authorized_proposal(run_id, approval.idempotency_key)
        if proposal.status is WritebackStatus.ROLLED_BACK:
            return proposal
        if (
            proposal.status is not WritebackStatus.COMPLETED
            or approval.decision is not HumanDecision.APPROVE_ROLLBACK
        ):
            raise WritebackError("Completed write-back and APPROVE_ROLLBACK are required")
        document_urn = proposal.snapshot.get("document_urn")
        if not isinstance(document_urn, str):
            raise WritebackError("Rollback requires the persisted write-back snapshot")

        proposal.status = WritebackStatus.ROLLBACK_PENDING
        self.repository.save(proposal)
        self._audit(run_id, "ROLLBACK_PENDING", {"document_urn": document_urn})
        await self.writer.supersede(
            document_urn,
            "Superseded by approved LineageGuard rollback.",
            proposal.target_asset_urn,
        )
        proposal.status = WritebackStatus.ROLLED_BACK
        self.repository.save(proposal)
        self._audit(
            run_id,
            "ROLLBACK_COMPLETED",
            {"document_urn": document_urn, "comment": approval.comment},
        )
        return proposal

    def get(self, run_id: str) -> WritebackProposal | None:
        return self.repository.get(run_id)

    def audit_events(self, run_id: str) -> list[AuditEvent]:
        return self.repository.events(run_id)

    def _authorized_proposal(
        self, run_id: str, idempotency_key: str
    ) -> WritebackProposal:
        proposal = self.repository.get(run_id)
        if not proposal or proposal.idempotency_key != idempotency_key:
            raise WritebackError("Unknown proposal or idempotency key")
        return proposal

    def _audit(self, run_id: str, event_type: str, detail: dict[str, object]) -> None:
        self.repository.add_event(
            AuditEvent(
                run_id=run_id,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                detail=detail,
            )
        )
