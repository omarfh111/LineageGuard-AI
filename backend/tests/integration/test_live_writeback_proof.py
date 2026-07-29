"""Explicitly approved proof that a DataHub document write-back completes.

This is intentionally skipped in normal CI. Running it creates then supersedes
one Analysis document in the configured local DataHub instance; it never
modifies a dataset, schema, lineage relationship, dbt job or warehouse.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import pytest

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import (
    AggregateDecision,
    ApprovalRequest,
    DeterministicValidation,
    HumanDecision,
    JudgeAggregation,
    JudgingResult,
    WritebackPreparationRequest,
)
from app.services.catalog_graph import catalog_from_search
from app.services.judging import validate_gate_zero
from app.services.remediation_planner import DeterministicRemediationPlanner
from app.services.writeback import (
    McpDocumentWriter,
    WritebackConflict,
    WritebackRepository,
    WritebackService,
)


pytestmark = pytest.mark.integration
_CONFIRMATION = "I_APPROVE_DEMO_DOCUMENT"


class CountingWriter:
    def __init__(self, delegate: McpDocumentWriter) -> None:
        self.delegate = delegate
        self.save_calls = 0
        self.supersede_calls = 0

    async def save(self, title: str, content: str, related_asset: str) -> str:
        self.save_calls += 1
        return await self.delegate.save(title, content, related_asset)

    async def supersede(
        self, document_urn: str, content: str, related_asset: str
    ) -> None:
        self.supersede_calls += 1
        await self.delegate.supersede(document_urn, content, related_asset)

    async def verify(
        self,
        document_urn: str,
        expected_title: str,
        expected_related_asset: str,
    ) -> bool:
        return await self.delegate.verify(
            document_urn, expected_title, expected_related_asset
        )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (
        os.getenv("RUN_DATAHUB_WRITEBACK_PROOF") == "1"
        and os.getenv("CONFIRM_LIVE_WRITEBACK") == _CONFIRMATION
    ),
    reason=(
        "This creates and then supersedes one DataHub Analysis document. "
        "Set RUN_DATAHUB_WRITEBACK_PROOF=1 and CONFIRM_LIVE_WRITEBACK=" + _CONFIRMATION
    ),
)
async def test_live_document_writeback_with_explicit_human_approval(tmp_path) -> None:
    settings = replace(get_settings(), datahub_writeback_enabled=True)
    client = DataHubMcpClient(settings)
    catalog = catalog_from_search(await client.search("*", num_results=10), "*")
    asset = next((node for node in catalog.nodes if node.urn.startswith("urn:li:dataset:")), None)
    assert asset is not None, "The local DataHub catalog must contain at least one dataset"

    # The judgement packet is deterministic and deliberately synthetic: this
    # test proves the MCP write and compensation path, not judge quality.
    from test_judging import judging_request

    request = judging_request()
    report = request.impact_report
    report.request.asset_urn = asset.urn
    report.evidence_bundle.source_asset_urn = asset.urn
    for item in report.evidence_bundle.items:
        item.asset_urn = asset.urn
        if "source_asset_urn" in item.raw_reference:
            item.raw_reference["source_asset_urn"] = asset.urn
        if "downstream_asset_urn" in item.raw_reference:
            item.raw_reference["downstream_asset_urn"] = asset.urn
    report.impacted_assets[0].asset_urn = asset.urn
    report.impacted_assets[0].lineage_path = [asset.urn]
    request.remediation_plan = DeterministicRemediationPlanner().plan(report)
    gate = validate_gate_zero(request)
    assert gate.passed, gate.errors
    result = JudgingResult(
        deterministic_validation=gate,
        openai_verdict=None,
        groq_verdict=None,
        aggregate_decision=JudgeAggregation(
            decision=AggregateDecision.FINALIZE_READ_ONLY,
            human_review_required=False,
            rationale="Synthetic double-PASS fixture for an explicitly approved live MCP proof.",
        ),
    )
    writer = CountingWriter(McpDocumentWriter(client))
    service = WritebackService(
        writer,
        WritebackRepository(f"sqlite:///{tmp_path / 'writeback-proof.db'}"),
    )
    preparation = WritebackPreparationRequest(
        judging_request=request,
        judging_result=result,
        idempotency_key="live-writeback-proof-v1",
    )
    proposal = service.prepare(preparation)
    approve = ApprovalRequest(
        decision=HumanDecision.APPROVE_REPORT,
        comment="Explicit local demo approval for the proof document.",
        idempotency_key=preparation.idempotency_key,
    )
    approval_results = await asyncio.gather(
        service.decide(proposal.run_id, approve),
        service.decide(proposal.run_id, approve),
        return_exceptions=True,
    )
    completed = next(
        result for result in approval_results if not isinstance(result, Exception)
    )
    assert completed.status == "COMPLETED"
    assert str(completed.snapshot["document_urn"]).startswith("urn:li:document:")
    assert writer.save_calls == 1
    assert sum(isinstance(result, WritebackConflict) for result in approval_results) <= 1

    approve_rollback = ApprovalRequest(
        decision=HumanDecision.APPROVE_ROLLBACK,
        comment="Clean up the proof document by superseding it.",
        idempotency_key=preparation.idempotency_key,
    )
    rollback_results = await asyncio.gather(
        service.rollback(proposal.run_id, approve_rollback),
        service.rollback(proposal.run_id, approve_rollback),
        return_exceptions=True,
    )
    rolled_back = next(
        result for result in rollback_results if not isinstance(result, Exception)
    )
    assert rolled_back.status == "ROLLED_BACK"
    assert writer.supersede_calls == 1
    assert [event.event_type for event in service.audit_events(proposal.run_id)] == [
        "WRITEBACK_PREPARED",
        "APPROVED",
        "WRITEBACK_PENDING",
        "WRITEBACK_COMPLETED",
        "ROLLBACK_PENDING",
        "ROLLBACK_COMPLETED",
    ]
