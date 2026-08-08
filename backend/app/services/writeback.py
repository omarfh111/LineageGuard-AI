"""Approval-gated document write-back with durable concurrency controls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    WritebackReconciliationAction,
    WritebackReconciliationRequest,
    WritebackStatus,
)
from app.services.run_store import sqlite_path


class DocumentWriter(Protocol):
    async def save(self, title: str, content: str, related_asset: str) -> str: ...

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None: ...

    async def verify(
        self,
        document_urn: str,
        expected_title: str,
        expected_related_asset: str,
    ) -> bool: ...


class WritebackError(ValueError):
    """Base class for safe write-back errors exposed by the API."""


class WritebackConflict(WritebackError):
    """The requested operation conflicts with a durable operation in progress."""


class WritebackOutcomeUnknown(WritebackError):
    """The external result is unknown and must not be retried automatically."""


class McpDocumentWriter:
    def __init__(self, client: DataHubMcpClient) -> None:
        self.client = client

    async def save(self, title: str, content: str, related_asset: str) -> str:
        result = await self.client.save_document(title, content, related_asset)
        match = re.search(r"urn:li:document:[A-Za-z0-9._-]+", json.dumps(result))
        if not match:
            raise WritebackOutcomeUnknown(
                "DataHub returned no document URN; external outcome requires reconciliation"
            )
        return match.group(0)

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None:
        result = await self.client.save_document(
            "Superseded LineageGuard analysis",
            content,
            related_asset,
            urn=document_urn,
        )
        if document_urn not in json.dumps(result):
            raise WritebackOutcomeUnknown(
                "DataHub did not confirm the compensated document URN"
            )

    async def verify(
        self,
        document_urn: str,
        expected_title: str,
        expected_related_asset: str,
    ) -> bool:
        result = await self.client.call_tool(
            "get_entities", {"urns": document_urn}
        )
        serialized = json.dumps(result, sort_keys=True)
        return all(
            expected in serialized
            for expected in (
                document_urn,
                expected_title,
                expected_related_asset,
            )
        )


@dataclass(frozen=True)
class WritebackOperationResult:
    proposal: WritebackProposal
    performed: bool


class WritebackRepository:
    """SQLite state machine with cross-thread/process compare-and-swap."""

    def __init__(self, database_url: str | None = None) -> None:
        self._path = sqlite_path(database_url or get_settings().database_url)
        self._uri = self._path == ":memory:"
        self._connect_target = (
            f"file:lineageguard-writeback-{uuid4().hex}?mode=memory&cache=shared"
            if self._uri
            else self._path
        )
        self._keeper: sqlite3.Connection | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._keeper = sqlite3.connect(
                self._connect_target, uri=True, timeout=30
            )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._connect_target, uri=self._uri, timeout=30
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            if self._path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writeback_proposals (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    report_hash TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    UNIQUE(idempotency_key, report_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_writeback_idempotency
                    ON writeback_proposals(idempotency_key);
                CREATE INDEX IF NOT EXISTS idx_writeback_report_hash
                    ON writeback_proposals(report_hash);
                CREATE TABLE IF NOT EXISTS writeback_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                """
            )

    def create(self, proposal: WritebackProposal) -> tuple[WritebackProposal, bool]:
        """Atomically create one proposal per key and per report."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT proposal_json FROM writeback_proposals
                    WHERE idempotency_key = ? OR report_hash = ?
                    """,
                    (proposal.idempotency_key, proposal.report_hash),
                ).fetchall()
                for row in rows:
                    existing = WritebackProposal.model_validate_json(
                        row["proposal_json"]
                    )
                    if (
                        existing.idempotency_key == proposal.idempotency_key
                        and existing.report_hash == proposal.report_hash
                    ):
                        connection.commit()
                        return existing, False
                    if existing.idempotency_key == proposal.idempotency_key:
                        raise WritebackConflict(
                            "Idempotency key was already used for another report"
                        )
                    raise WritebackConflict(
                        "This report already has a proposal under another idempotency key"
                    )

                connection.execute(
                    """
                    INSERT INTO writeback_proposals(
                        run_id, idempotency_key, report_hash, proposal_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        proposal.run_id,
                        proposal.idempotency_key,
                        proposal.report_hash,
                        proposal.model_dump_json(),
                    ),
                )
                self._insert_event(
                    connection,
                    proposal.run_id,
                    "WRITEBACK_PREPARED",
                    {"report_hash": proposal.report_hash},
                )
                connection.commit()
                return proposal, True
            except BaseException:
                connection.rollback()
                raise

    def get(self, run_id: str) -> WritebackProposal | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT proposal_json FROM writeback_proposals WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return (
            WritebackProposal.model_validate_json(row["proposal_json"])
            if row
            else None
        )

    def transition(
        self,
        run_id: str,
        idempotency_key: str,
        expected: set[WritebackStatus],
        target: WritebackStatus,
        events: list[tuple[str, dict[str, object]]],
        *,
        snapshot: dict[str, object] | None = None,
        operation_id: str | None = None,
    ) -> tuple[WritebackProposal, bool]:
        """Commit state and audit events in one SQLite transaction."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT proposal_json FROM writeback_proposals WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if not row:
                    raise WritebackError("Unknown proposal or idempotency key")
                proposal = WritebackProposal.model_validate_json(
                    row["proposal_json"]
                )
                if proposal.idempotency_key != idempotency_key:
                    raise WritebackError("Unknown proposal or idempotency key")
                if proposal.status not in expected:
                    connection.commit()
                    return proposal, False
                if operation_id is not None:
                    active = proposal.snapshot.get("active_operation")
                    if (
                        not isinstance(active, dict)
                        or active.get("operation_id") != operation_id
                    ):
                        connection.commit()
                        return proposal, False

                proposal.status = target
                if snapshot is not None:
                    proposal.snapshot = snapshot
                self._update(connection, proposal)
                for event_type, detail in events:
                    self._insert_event(connection, run_id, event_type, detail)
                connection.commit()
                return proposal, True
            except BaseException:
                connection.rollback()
                raise

    def recover_stale_inflight(self, stale_after_seconds: int) -> int:
        """Fail closed after a crashed worker leaves an external result unknown."""

        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        recovered = 0
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT proposal_json FROM writeback_proposals"
                ).fetchall()
                for row in rows:
                    proposal = WritebackProposal.model_validate_json(
                        row["proposal_json"]
                    )
                    if proposal.status not in {
                        WritebackStatus.WRITEBACK_PENDING,
                        WritebackStatus.ROLLBACK_PENDING,
                    }:
                        continue
                    active = proposal.snapshot.get("active_operation")
                    started_at = (
                        active.get("started_at") if isinstance(active, dict) else None
                    )
                    if not isinstance(started_at, str):
                        continue
                    try:
                        started = datetime.fromisoformat(started_at)
                    except ValueError:
                        continue
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=UTC)
                    if started > cutoff:
                        continue

                    if proposal.status is WritebackStatus.WRITEBACK_PENDING:
                        proposal.status = WritebackStatus.WRITEBACK_UNCERTAIN
                        event_type = "WRITEBACK_STALE_RECONCILIATION_REQUIRED"
                    else:
                        proposal.status = WritebackStatus.ROLLBACK_UNCERTAIN
                        event_type = "ROLLBACK_STALE_RETRY_REQUIRED"
                    proposal.snapshot["last_error"] = {
                        "code": "STALE_INFLIGHT_OPERATION",
                        "outcome": "UNKNOWN",
                    }
                    self._update(connection, proposal)
                    self._insert_event(
                        connection,
                        proposal.run_id,
                        event_type,
                        {"operation_id": active.get("operation_id")},
                    )
                    recovered += 1
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return recovered

    def events(self, run_id: str) -> list[AuditEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM writeback_audit_events
                WHERE run_id = ? ORDER BY event_id
                """,
                (run_id,),
            ).fetchall()
        return [
            AuditEvent.model_validate_json(row["event_json"]) for row in rows
        ]

    @staticmethod
    def _update(
        connection: sqlite3.Connection, proposal: WritebackProposal
    ) -> None:
        connection.execute(
            "UPDATE writeback_proposals SET proposal_json = ? WHERE run_id = ?",
            (proposal.model_dump_json(), proposal.run_id),
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        detail: dict[str, object],
    ) -> None:
        event = AuditEvent(
            run_id=run_id,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            detail=detail,
        )
        connection.execute(
            """
            INSERT INTO writeback_audit_events(run_id, event_json)
            VALUES (?, ?)
            """,
            (run_id, event.model_dump_json()),
        )


class WritebackService:
    def __init__(
        self,
        writer: DocumentWriter,
        repository: WritebackRepository | None = None,
        *,
        stale_after_seconds: int = 300,
    ) -> None:
        self.writer = writer
        self.repository = repository or WritebackRepository("sqlite:///:memory:")
        self.stale_after_seconds = max(30, stale_after_seconds)
        self.repository.recover_stale_inflight(self.stale_after_seconds)

    def prepare(self, request: WritebackPreparationRequest) -> WritebackProposal:
        result = request.judging_result
        if not result.deterministic_validation.passed:
            raise WritebackError("Gate 0 must pass before write-back preparation")
        if (
            not result.aggregate_decision
            or result.aggregate_decision.decision != "FINALIZE_READ_ONLY"
        ):
            raise WritebackError(
                "Double PASS is required before write-back preparation"
            )

        report = request.judging_request.impact_report
        payload = report.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        proposal = WritebackProposal(
            run_id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            report_hash=digest,
            target_asset_urn=report.request.asset_urn,
            document_title=f"LineageGuard analysis {digest[:12]}",
            document_content=payload,
            snapshot={
                "document_urn": None,
                "exists": False,
                "pre_write_document": None,
                "active_operation": None,
                "last_error": None,
            },
        )
        return self.repository.create(proposal)[0]

    async def decide(
        self, run_id: str, approval: ApprovalRequest
    ) -> WritebackProposal:
        return (await self.decide_with_outcome(run_id, approval)).proposal

    async def decide_with_outcome(
        self, run_id: str, approval: ApprovalRequest
    ) -> WritebackOperationResult:
        proposal = self._authorized_proposal(run_id, approval.idempotency_key)
        if proposal.status is WritebackStatus.COMPLETED:
            return WritebackOperationResult(proposal, False)
        if proposal.status is WritebackStatus.REJECTED:
            if approval.decision is HumanDecision.REJECT:
                return WritebackOperationResult(proposal, False)
            raise WritebackConflict("A rejected proposal cannot be approved")
        if proposal.status is WritebackStatus.REVISION_REQUESTED:
            if approval.decision is HumanDecision.REQUEST_REVISION:
                return WritebackOperationResult(proposal, False)
            raise WritebackConflict(
                "A proposal awaiting revision cannot be approved"
            )
        if proposal.status is WritebackStatus.WRITEBACK_PENDING:
            raise WritebackConflict("Write-back is already in progress")
        if proposal.status in {
            WritebackStatus.WRITEBACK_UNCERTAIN,
            WritebackStatus.FAILED,
        }:
            raise WritebackOutcomeUnknown(
                "Write-back outcome is unknown; reconcile it before any retry"
            )

        if approval.decision is HumanDecision.REJECT:
            rejected, changed = self.repository.transition(
                run_id,
                approval.idempotency_key,
                {WritebackStatus.PENDING_APPROVAL},
                WritebackStatus.REJECTED,
                [("REJECTED", {"comment": approval.comment})],
            )
            if not changed and rejected.status is not WritebackStatus.REJECTED:
                raise WritebackConflict(
                    f"Proposal cannot be rejected from {rejected.status}"
                )
            return WritebackOperationResult(rejected, changed)
        if approval.decision is HumanDecision.REQUEST_REVISION:
            revision, changed = self.repository.transition(
                run_id,
                approval.idempotency_key,
                {WritebackStatus.PENDING_APPROVAL},
                WritebackStatus.REVISION_REQUESTED,
                [
                    (
                        "REVISION_REQUESTED",
                        {"comment": approval.comment},
                    )
                ],
            )
            if (
                not changed
                and revision.status is not WritebackStatus.REVISION_REQUESTED
            ):
                raise WritebackConflict(
                    f"Revision cannot be requested from {revision.status}"
                )
            return WritebackOperationResult(revision, changed)
        if approval.decision is not HumanDecision.APPROVE_REPORT:
            raise WritebackError(
                "Only APPROVE_REPORT may execute this write-back"
            )

        operation_id = str(uuid4())
        snapshot = dict(proposal.snapshot)
        snapshot["active_operation"] = {
            "operation_id": operation_id,
            "kind": "WRITEBACK",
            "started_at": datetime.now(UTC).isoformat(),
        }
        snapshot["last_error"] = None
        pending, claimed = self.repository.transition(
            run_id,
            approval.idempotency_key,
            {WritebackStatus.PENDING_APPROVAL, WritebackStatus.APPROVED},
            WritebackStatus.WRITEBACK_PENDING,
            [
                ("APPROVED", {"comment": approval.comment}),
                ("WRITEBACK_PENDING", {"operation_id": operation_id}),
            ],
            snapshot=snapshot,
        )
        if not claimed:
            if pending.status is WritebackStatus.COMPLETED:
                return WritebackOperationResult(pending, False)
            if pending.status is WritebackStatus.WRITEBACK_PENDING:
                raise WritebackConflict("Write-back is already in progress")
            raise WritebackConflict(
                f"Proposal cannot be approved from {pending.status}"
            )

        try:
            document_urn = await self.writer.save(
                pending.document_title,
                pending.document_content,
                pending.target_asset_urn,
            )
        except asyncio.CancelledError:
            self._mark_unknown(
                pending, operation_id, "WRITEBACK_CANCELLED", "CancelledError"
            )
            raise
        except Exception as error:
            self._mark_unknown(
                pending, operation_id, "WRITEBACK_OUTCOME_UNKNOWN", type(error).__name__
            )
            raise WritebackOutcomeUnknown(
                "DataHub write result is unknown; automatic retry is blocked"
            ) from error

        # A tool acknowledgement alone is not enough to call this a completed
        # write. Re-read the exact DataHub document and verify its immutable
        # identity, title, and related asset before recording COMPLETED. If
        # confirmation cannot be established, preserve the operation in an
        # explicit reconciliation state rather than showing a false success.
        try:
            document_verified = await self.writer.verify(
                document_urn,
                pending.document_title,
                pending.target_asset_urn,
            )
        except asyncio.CancelledError:
            self._mark_unknown(
                pending, operation_id, "WRITEBACK_VERIFY_CANCELLED", "CancelledError"
            )
            raise
        except Exception as error:
            self._mark_unknown(
                pending, operation_id, "WRITEBACK_VERIFY_UNKNOWN", type(error).__name__
            )
            raise WritebackOutcomeUnknown(
                "DataHub accepted the document but post-write verification is unknown; reconcile before retrying"
            ) from error
        if not document_verified:
            self._mark_unknown(
                pending, operation_id, "WRITEBACK_VERIFY_FAILED", "Document identity could not be verified"
            )
            raise WritebackOutcomeUnknown(
                "DataHub document could not be verified after write; reconcile before retrying"
            )

        completed_snapshot = dict(pending.snapshot)
        completed_snapshot.update(
            {
                "document_urn": document_urn,
                "exists": True,
                "pre_write_document": None,
                "active_operation": None,
                "last_error": None,
                "post_write_verified": True,
            }
        )
        try:
            completed, changed = self.repository.transition(
                run_id,
                approval.idempotency_key,
                {WritebackStatus.WRITEBACK_PENDING},
                WritebackStatus.COMPLETED,
                [
                    (
                        "WRITEBACK_COMPLETED",
                        {
                            "document_urn": document_urn,
                            "operation_id": operation_id,
                        },
                    )
                ],
                snapshot=completed_snapshot,
                operation_id=operation_id,
            )
        except Exception as error:
            raise WritebackOutcomeUnknown(
                "DataHub may contain the document but local completion failed; "
                "automatic retry is blocked"
            ) from error
        if not changed:
            raise WritebackOutcomeUnknown(
                "DataHub may contain the document but operation ownership changed"
            )
        return WritebackOperationResult(completed, True)

    async def rollback(
        self, run_id: str, approval: ApprovalRequest
    ) -> WritebackProposal:
        return (await self.rollback_with_outcome(run_id, approval)).proposal

    async def rollback_with_outcome(
        self, run_id: str, approval: ApprovalRequest
    ) -> WritebackOperationResult:
        proposal = self._authorized_proposal(run_id, approval.idempotency_key)
        if proposal.status is WritebackStatus.ROLLED_BACK:
            return WritebackOperationResult(proposal, False)
        if proposal.status is WritebackStatus.ROLLBACK_PENDING:
            raise WritebackConflict("Rollback is already in progress")
        if approval.decision is not HumanDecision.APPROVE_ROLLBACK:
            raise WritebackError("APPROVE_ROLLBACK is required")
        if proposal.status not in {
            WritebackStatus.COMPLETED,
            WritebackStatus.ROLLBACK_UNCERTAIN,
        }:
            raise WritebackConflict(
                "Completed or uncertain rollback state is required"
            )
        document_urn = proposal.snapshot.get("document_urn")
        if not isinstance(document_urn, str):
            raise WritebackError(
                "Rollback requires the persisted write-back snapshot"
            )

        operation_id = str(uuid4())
        snapshot = dict(proposal.snapshot)
        snapshot["active_operation"] = {
            "operation_id": operation_id,
            "kind": "ROLLBACK",
            "started_at": datetime.now(UTC).isoformat(),
        }
        snapshot["last_error"] = None
        pending, claimed = self.repository.transition(
            run_id,
            approval.idempotency_key,
            {
                WritebackStatus.COMPLETED,
                WritebackStatus.ROLLBACK_UNCERTAIN,
            },
            WritebackStatus.ROLLBACK_PENDING,
            [
                (
                    "ROLLBACK_PENDING",
                    {
                        "document_urn": document_urn,
                        "operation_id": operation_id,
                        "comment": approval.comment,
                    },
                )
            ],
            snapshot=snapshot,
        )
        if not claimed:
            if pending.status is WritebackStatus.ROLLED_BACK:
                return WritebackOperationResult(pending, False)
            raise WritebackConflict(
                f"Rollback cannot start from {pending.status}"
            )

        try:
            await self.writer.supersede(
                document_urn,
                "Superseded by approved LineageGuard rollback.",
                pending.target_asset_urn,
            )
        except asyncio.CancelledError:
            self._mark_unknown(
                pending, operation_id, "ROLLBACK_CANCELLED", "CancelledError"
            )
            raise
        except Exception as error:
            self._mark_unknown(
                pending, operation_id, "ROLLBACK_OUTCOME_UNKNOWN", type(error).__name__
            )
            raise WritebackOutcomeUnknown(
                "Rollback result is unknown; another explicit rollback approval "
                "may safely retry the same document URN"
            ) from error

        rolled_snapshot = dict(pending.snapshot)
        rolled_snapshot.update(
            {"active_operation": None, "last_error": None}
        )
        rolled_back, changed = self.repository.transition(
            run_id,
            approval.idempotency_key,
            {WritebackStatus.ROLLBACK_PENDING},
            WritebackStatus.ROLLED_BACK,
            [
                (
                    "ROLLBACK_COMPLETED",
                    {
                        "document_urn": document_urn,
                        "operation_id": operation_id,
                        "comment": approval.comment,
                    },
                )
            ],
            snapshot=rolled_snapshot,
            operation_id=operation_id,
        )
        if not changed:
            raise WritebackOutcomeUnknown(
                "Rollback may have completed but local confirmation is unknown"
            )
        return WritebackOperationResult(rolled_back, True)

    async def reconcile(
        self, run_id: str, request: WritebackReconciliationRequest
    ) -> WritebackProposal:
        proposal = self._authorized_proposal(run_id, request.idempotency_key)
        if proposal.status not in {
            WritebackStatus.WRITEBACK_UNCERTAIN,
            WritebackStatus.FAILED,
        }:
            raise WritebackConflict(
                "Only an uncertain write-back can be reconciled"
            )
        snapshot = dict(proposal.snapshot)
        snapshot["active_operation"] = None
        snapshot["last_error"] = None

        if request.action is WritebackReconciliationAction.ADOPT_COMPLETED_DOCUMENT:
            if not request.document_urn or not re.fullmatch(
                r"urn:li:document:[A-Za-z0-9._-]+", request.document_urn
            ):
                raise WritebackError(
                    "A valid verified DataHub document URN is required"
                )
            if not await self.writer.verify(
                request.document_urn,
                proposal.document_title,
                proposal.target_asset_urn,
            ):
                raise WritebackError(
                    "The document does not match this proposal title and related asset"
                )
            snapshot.update(
                {
                    "document_urn": request.document_urn,
                    "exists": True,
                    "reconciliation": "HUMAN_VERIFIED_EXISTING_DOCUMENT",
                }
            )
            target = WritebackStatus.COMPLETED
            event_type = "WRITEBACK_RECONCILED_COMPLETED"
            detail = {
                "document_urn": request.document_urn,
                "comment": request.comment,
            }
        else:
            if request.document_urn is not None:
                raise WritebackError(
                    "document_urn must be omitted when no document was created"
                )
            snapshot.update(
                {
                    "document_urn": None,
                    "exists": False,
                    "reconciliation": "HUMAN_VERIFIED_NO_DOCUMENT",
                }
            )
            target = WritebackStatus.PENDING_APPROVAL
            event_type = "WRITEBACK_RETRY_ENABLED"
            detail = {"comment": request.comment}

        reconciled, changed = self.repository.transition(
            run_id,
            request.idempotency_key,
            {
                WritebackStatus.WRITEBACK_UNCERTAIN,
                WritebackStatus.FAILED,
            },
            target,
            [(event_type, detail)],
            snapshot=snapshot,
        )
        if not changed:
            raise WritebackConflict(
                f"Proposal cannot be reconciled from {reconciled.status}"
            )
        return reconciled

    def get(self, run_id: str) -> WritebackProposal | None:
        self.repository.recover_stale_inflight(self.stale_after_seconds)
        return self.repository.get(run_id)

    def audit_events(self, run_id: str) -> list[AuditEvent]:
        return self.repository.events(run_id)

    def _authorized_proposal(
        self, run_id: str, idempotency_key: str
    ) -> WritebackProposal:
        self.repository.recover_stale_inflight(self.stale_after_seconds)
        proposal = self.repository.get(run_id)
        if not proposal or proposal.idempotency_key != idempotency_key:
            raise WritebackError("Unknown proposal or idempotency key")
        return proposal

    def _mark_unknown(
        self,
        proposal: WritebackProposal,
        operation_id: str,
        event_type: str,
        error_code: str,
    ) -> None:
        if proposal.status is WritebackStatus.WRITEBACK_PENDING:
            target = WritebackStatus.WRITEBACK_UNCERTAIN
        else:
            target = WritebackStatus.ROLLBACK_UNCERTAIN
        snapshot = dict(proposal.snapshot)
        snapshot["last_error"] = {
            "code": error_code,
            "outcome": "UNKNOWN",
        }
        try:
            self.repository.transition(
                proposal.run_id,
                proposal.idempotency_key,
                {proposal.status},
                target,
                [(event_type, {"operation_id": operation_id, "code": error_code})],
                snapshot=snapshot,
                operation_id=operation_id,
            )
        except Exception:
            # Never mask the original external failure. A fresh process will
            # recover a stale pending operation to an uncertain state.
            pass
