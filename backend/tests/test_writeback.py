from pathlib import Path

import pytest

from app.domain.contracts import (
    AggregateDecision,
    ApprovalRequest,
    DeterministicValidation,
    JudgeAggregation,
    JudgingResult,
    WritebackPreparationRequest,
)
from app.services.writeback import WritebackRepository, WritebackService


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


def request(key: str = "idempotency-key") -> WritebackPreparationRequest:
    from test_judging import judging_request

    judging_result = JudgingResult(
        deterministic_validation=DeterministicValidation(passed=True, errors=[]),
        openai_verdict=None,
        groq_verdict=None,
        aggregate_decision=JudgeAggregation(
            decision=AggregateDecision.FINALIZE_READ_ONLY,
            human_review_required=False,
            rationale="test",
        ),
    )
    return WritebackPreparationRequest(
        judging_request=judging_request(),
        judging_result=judging_result,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_writeback_is_persistent_idempotent_and_compensated() -> None:
    database_path = Path(__file__).with_name(".writeback-workflow-test.db")
    database_path.unlink(missing_ok=True)
    database_url = f"sqlite:///{database_path}"
    writer = FakeWriter()
    service = WritebackService(writer, WritebackRepository(database_url))

    preparation = request()
    proposal = service.prepare(preparation)
    assert service.prepare(preparation).run_id == proposal.run_id

    approval = ApprovalRequest(
        decision="APPROVE_REPORT", comment="approved", idempotency_key="idempotency-key"
    )
    await service.decide(proposal.run_id, approval)
    await service.decide(proposal.run_id, approval)
    assert len(writer.saved) == 1

    reloaded = WritebackService(writer, WritebackRepository(database_url))
    assert reloaded.get(proposal.run_id).status == "COMPLETED"
    assert reloaded.get(proposal.run_id).snapshot["document_urn"] == "urn:li:document:run-1"

    rollback = ApprovalRequest(
        decision="APPROVE_ROLLBACK", comment="rollback", idempotency_key="idempotency-key"
    )
    await reloaded.rollback(proposal.run_id, rollback)
    assert writer.superseded == [("urn:li:document:run-1", proposal.target_asset_urn)]
    assert reloaded.get(proposal.run_id).status == "ROLLED_BACK"
    assert [event.event_type for event in reloaded.audit_events(proposal.run_id)] == [
        "WRITEBACK_PREPARED",
        "APPROVED",
        "WRITEBACK_PENDING",
        "WRITEBACK_COMPLETED",
        "ROLLBACK_PENDING",
        "ROLLBACK_COMPLETED",
    ]
    database_path.unlink()
