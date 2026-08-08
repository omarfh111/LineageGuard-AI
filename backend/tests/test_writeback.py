import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.contracts import (
    AggregateDecision,
    ApprovalRequest,
    DeterministicValidation,
    JudgeAggregation,
    JudgingResult,
    WritebackPreparationRequest,
    WritebackProposalView,
    WritebackReconciliationRequest,
    WritebackStatus,
)
from app.services.writeback import (
    WritebackConflict,
    WritebackError,
    WritebackOutcomeUnknown,
    WritebackRepository,
    WritebackService,
)


class FakeWriter:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []
        self.superseded: list[tuple[str, str]] = []

    async def save(self, title: str, content: str, related_asset: str) -> str:
        self.saved.append((title, related_asset))
        return "urn:li:document:run-1"

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None:
        self.superseded.append((document_urn, related_asset))

    async def verify(
        self,
        document_urn: str,
        expected_title: str,
        expected_related_asset: str,
    ) -> bool:
        return (
            document_urn in {"urn:li:document:run-1", "urn:li:document:concurrent-run", "urn:li:document:verified-existing-document"}
            and expected_title.startswith("LineageGuard analysis ")
            and expected_related_asset.startswith("urn:li:")
        )


class BlockingWriter(FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def save(self, title: str, content: str, related_asset: str) -> str:
        self.saved.append((title, related_asset))
        self.started.set()
        await self.release.wait()
        return "urn:li:document:concurrent-run"


class AmbiguousWriteWriter(FakeWriter):
    async def save(self, title: str, content: str, related_asset: str) -> str:
        self.saved.append((title, related_asset))
        raise TimeoutError("response lost after the remote operation")


class AmbiguousRollbackWriter(FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.fail_rollback_once = True

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None:
        self.superseded.append((document_urn, related_asset))
        if self.fail_rollback_once:
            self.fail_rollback_once = False
            raise TimeoutError("response lost after compensation")


def request(
    key: str = "idempotency-key", *, reason: str | None = None
) -> WritebackPreparationRequest:
    from test_judging import judging_request

    judging = judging_request()
    if reason is not None:
        judging.impact_report.request.reason = reason
    judging_result = JudgingResult(
        deterministic_validation=DeterministicValidation(
            passed=True, errors=[]
        ),
        openai_verdict=None,
        groq_verdict=None,
        aggregate_decision=JudgeAggregation(
            decision=AggregateDecision.FINALIZE_READ_ONLY,
            human_review_required=False,
            rationale="test",
        ),
    )
    return WritebackPreparationRequest(
        judging_request=judging,
        judging_result=judging_result,
        idempotency_key=key,
    )


def approval(
    decision: str = "APPROVE_REPORT", key: str = "idempotency-key"
) -> ApprovalRequest:
    return ApprovalRequest(
        decision=decision,
        comment=f"{decision} explicitly confirmed in test",
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_writeback_is_persistent_idempotent_and_compensated(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'writeback.db'}"
    writer = FakeWriter()
    service = WritebackService(writer, WritebackRepository(database_url))

    preparation = request()
    proposal = service.prepare(preparation)
    assert service.prepare(preparation).run_id == proposal.run_id

    await service.decide(proposal.run_id, approval())
    await service.decide(proposal.run_id, approval())
    assert len(writer.saved) == 1

    reloaded = WritebackService(writer, WritebackRepository(database_url))
    assert reloaded.get(proposal.run_id).status == "COMPLETED"
    assert (
        reloaded.get(proposal.run_id).snapshot["document_urn"]
        == "urn:li:document:run-1"
    )

    await reloaded.rollback(
        proposal.run_id, approval("APPROVE_ROLLBACK")
    )
    assert writer.superseded == [
        ("urn:li:document:run-1", proposal.target_asset_urn)
    ]
    assert reloaded.get(proposal.run_id).status == "ROLLED_BACK"
    assert [
        event.event_type for event in reloaded.audit_events(proposal.run_id)
    ] == [
        "WRITEBACK_PREPARED",
        "APPROVED",
        "WRITEBACK_PENDING",
        "WRITEBACK_COMPLETED",
        "ROLLBACK_PENDING",
        "ROLLBACK_COMPLETED",
    ]


@pytest.mark.asyncio
async def test_concurrent_approvals_claim_one_external_write(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    writer = BlockingWriter()
    service_a = WritebackService(writer, WritebackRepository(database_url))
    service_b = WritebackService(writer, WritebackRepository(database_url))
    proposal = service_a.prepare(request())

    first = asyncio.create_task(service_a.decide(proposal.run_id, approval()))
    await writer.started.wait()
    with pytest.raises(WritebackConflict, match="already in progress"):
        await service_b.decide(proposal.run_id, approval())
    writer.release.set()

    completed = await first
    assert completed.status == "COMPLETED"
    assert len(writer.saved) == 1
    assert [
        event.event_type for event in service_a.audit_events(proposal.run_id)
    ].count("WRITEBACK_COMPLETED") == 1


@pytest.mark.asyncio
async def test_concurrent_prepare_returns_one_proposal(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'prepare.db'}"
    service_a = WritebackService(FakeWriter(), WritebackRepository(database_url))
    service_b = WritebackService(FakeWriter(), WritebackRepository(database_url))
    preparation = request()

    first, second = await asyncio.gather(
        asyncio.to_thread(service_a.prepare, preparation),
        asyncio.to_thread(service_b.prepare, preparation),
    )

    assert first.run_id == second.run_id
    assert [
        event.event_type for event in service_a.audit_events(first.run_id)
    ] == ["WRITEBACK_PREPARED"]


def test_idempotency_key_and_report_hash_cannot_be_rebound(tmp_path) -> None:
    service = WritebackService(
        FakeWriter(),
        WritebackRepository(f"sqlite:///{tmp_path / 'binding.db'}"),
    )
    original = request()
    service.prepare(original)

    with pytest.raises(WritebackConflict, match="another report"):
        service.prepare(request(reason="A different approved report."))
    rebound = original.model_copy(deep=True)
    rebound.idempotency_key = "different-idempotency-key"
    with pytest.raises(WritebackConflict, match="another idempotency key"):
        service.prepare(rebound)


@pytest.mark.asyncio
async def test_unknown_create_outcome_blocks_retry_until_reconciled(
    tmp_path,
) -> None:
    writer = AmbiguousWriteWriter()
    service = WritebackService(
        writer,
        WritebackRepository(f"sqlite:///{tmp_path / 'unknown.db'}"),
    )
    proposal = service.prepare(request())

    with pytest.raises(WritebackOutcomeUnknown):
        await service.decide(proposal.run_id, approval())
    assert service.get(proposal.run_id).status == "WRITEBACK_UNCERTAIN"

    with pytest.raises(
        WritebackOutcomeUnknown, match="reconcile it before any retry"
    ):
        await service.decide(proposal.run_id, approval())
    assert len(writer.saved) == 1

    reconciled = await service.reconcile(
        proposal.run_id,
        WritebackReconciliationRequest(
            action="ADOPT_COMPLETED_DOCUMENT",
            comment="Verified the exact title and related asset in DataHub.",
            idempotency_key="idempotency-key",
            document_urn="urn:li:document:verified-existing-document",
        ),
    )
    assert reconciled.status == "COMPLETED"
    assert (
        reconciled.snapshot["document_urn"]
        == "urn:li:document:verified-existing-document"
    )
    assert len(writer.saved) == 1


@pytest.mark.asyncio
async def test_reconciliation_rejects_an_unrelated_document_urn(
    tmp_path,
) -> None:
    writer = AmbiguousWriteWriter()
    service = WritebackService(
        writer,
        WritebackRepository(f"sqlite:///{tmp_path / 'unrelated.db'}"),
    )
    proposal = service.prepare(request())

    with pytest.raises(WritebackOutcomeUnknown):
        await service.decide(proposal.run_id, approval())

    with pytest.raises(WritebackError, match="does not match this proposal"):
        await service.reconcile(
            proposal.run_id,
            WritebackReconciliationRequest(
                action="ADOPT_COMPLETED_DOCUMENT",
                comment="This URN belongs to another operation.",
                idempotency_key="idempotency-key",
                document_urn="urn:li:document:unrelated-document",
            ),
        )

    assert service.get(proposal.run_id).status == "WRITEBACK_UNCERTAIN"
    assert len(writer.saved) == 1


@pytest.mark.asyncio
async def test_failed_compensation_is_retryable_only_on_same_document(
    tmp_path,
) -> None:
    writer = AmbiguousRollbackWriter()
    service = WritebackService(
        writer,
        WritebackRepository(f"sqlite:///{tmp_path / 'rollback.db'}"),
    )
    proposal = service.prepare(request())
    await service.decide(proposal.run_id, approval())

    with pytest.raises(WritebackOutcomeUnknown):
        await service.rollback(
            proposal.run_id, approval("APPROVE_ROLLBACK")
        )
    uncertain = service.get(proposal.run_id)
    assert uncertain.status == "ROLLBACK_UNCERTAIN"
    assert uncertain.snapshot["document_urn"] == "urn:li:document:run-1"

    completed = await service.rollback(
        proposal.run_id, approval("APPROVE_ROLLBACK")
    )
    assert completed.status == "ROLLED_BACK"
    assert writer.superseded == [
        ("urn:li:document:run-1", proposal.target_asset_urn),
        ("urn:li:document:run-1", proposal.target_asset_urn),
    ]
    assert len(writer.saved) == 1


def test_stale_pending_operation_becomes_uncertain(tmp_path) -> None:
    repository = WritebackRepository(f"sqlite:///{tmp_path / 'stale.db'}")
    service = WritebackService(FakeWriter(), repository)
    proposal = service.prepare(request())
    operation_id = "stale-operation"
    snapshot = dict(proposal.snapshot)
    snapshot["active_operation"] = {
        "operation_id": operation_id,
        "kind": "WRITEBACK",
        "started_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
    }
    pending, changed = repository.transition(
        proposal.run_id,
        proposal.idempotency_key,
        {WritebackStatus.PENDING_APPROVAL},
        WritebackStatus.WRITEBACK_PENDING,
        [("WRITEBACK_PENDING", {"operation_id": operation_id})],
        snapshot=snapshot,
    )
    assert changed and pending.status == "WRITEBACK_PENDING"

    assert repository.recover_stale_inflight(30) == 1
    assert repository.get(proposal.run_id).status == "WRITEBACK_UNCERTAIN"


@pytest.mark.asyncio
async def test_revision_request_never_calls_writer(tmp_path) -> None:
    writer = FakeWriter()
    service = WritebackService(
        writer,
        WritebackRepository(f"sqlite:///{tmp_path / 'revision.db'}"),
    )
    proposal = service.prepare(request())

    revised = await service.decide(
        proposal.run_id, approval("REQUEST_REVISION")
    )

    assert revised.status == "REVISION_REQUESTED"
    assert writer.saved == []


def test_public_proposal_never_exposes_approval_key(tmp_path) -> None:
    service = WritebackService(
        FakeWriter(),
        WritebackRepository(f"sqlite:///{tmp_path / 'public.db'}"),
    )
    proposal = service.prepare(request())

    public = WritebackProposalView.from_proposal(proposal).model_dump()

    assert "idempotency_key" not in public


def test_in_memory_repository_is_shared_across_connections() -> None:
    service = WritebackService(
        FakeWriter(), WritebackRepository("sqlite:///:memory:")
    )

    proposal = service.prepare(request())

    assert service.get(proposal.run_id).run_id == proposal.run_id
