from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.v1.judging import get_judging_service
from app.domain.contracts import (
    ChangeRequest,
    ClaimType,
    EvidenceBundle,
    EvidenceItem,
    ImpactItem,
    ImpactReport,
    JudgeProvider,
    JudgeScores,
    JudgeStatus,
    JudgeVerdict,
    JudgingRequest,
    RiskAssessment,
    RiskComponents,
)
from app.main import app
from app.services.judging import (
    JudgingService,
    _judge_packet,
    _verdict_json_schema,
    aggregate_verdicts,
    validate_gate_zero,
)
from app.services.remediation_planner import DeterministicRemediationPlanner

SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
DOWNSTREAM_URN = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"


def judging_request() -> JudgingRequest:
    request = ChangeRequest(
        asset_urn=SOURCE_URN,
        change_type="DROP_COLUMN",
        column_name="customer_status",
        reason="A governed source field replaces this contract.",
        environment="DEMO",
    )
    report = ImpactReport(
        request=request,
        evidence_bundle=EvidenceBundle(
            source_asset_urn=SOURCE_URN,
            items=[
                EvidenceItem(
                    evidence_id="ev_schema_source",
                    tool="list_schema_fields",
                    asset_urn=SOURCE_URN,
                    claim_type=ClaimType.SCHEMA_FIELD,
                    raw_reference={"field_names": ["customer_status"]},
                    retrieved_at=datetime.now(UTC),
                ),
                EvidenceItem(
                    evidence_id="ev_lineage_001",
                    tool="get_lineage",
                    asset_urn=DOWNSTREAM_URN,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={},
                    retrieved_at=datetime.now(UTC),
                ),
            ],
        ),
        blast_radius=1,
        impacted_assets=[
            ImpactItem(
                asset_urn=DOWNSTREAM_URN,
                asset_type="DATASET",
                lineage_path=[SOURCE_URN, DOWNSTREAM_URN],
                owner_urns=["urn:li:corpuser:owner"],
                platform_urn="urn:li:dataPlatform:tableau",
                criticality="HIGH",
                evidence_ids=["ev_lineage_001"],
            )
        ],
        missing_metadata=[],
        risk_assessment=RiskAssessment(
            score=45,
            level="MEDIUM",
            components=RiskComponents(
                change_severity=90,
                blast_radius=10,
                asset_criticality=75,
                cross_platform_impact=0,
                metadata_uncertainty=0,
            ),
            explanation=[],
        ),
        confidence=1,
    )
    return JudgingRequest(
        impact_report=report,
        remediation_plan=DeterministicRemediationPlanner().plan(report),
    )


def verdict(provider: JudgeProvider, status: JudgeStatus) -> JudgeVerdict:
    return JudgeVerdict(
        judge_provider=provider,
        judge_model="test-model",
        verdict=status,
        scores=JudgeScores(
            grounding=5 if status is JudgeStatus.PASS else 0,
            technical_correctness=5 if status is JudgeStatus.PASS else 0,
            completeness=5 if status is JudgeStatus.PASS else 0,
            safety=5 if status is JudgeStatus.PASS else 0,
            actionability=5 if status is JudgeStatus.PASS else 0,
        ),
        critical_errors=[] if status is JudgeStatus.PASS else ["test error"],
        non_critical_issues=[],
        repair_instructions=[],
        confidence=1 if status is JudgeStatus.PASS else 0,
    )


class FakeJudge:
    def __init__(self, result: JudgeVerdict) -> None:
        self.result = result
        self.calls = 0

    async def evaluate(self, request: JudgingRequest) -> JudgeVerdict:
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_gate_zero_blocks_judges_when_evidence_is_invalid() -> None:
    request = judging_request()
    request.impact_report.impacted_assets[0].evidence_ids = ["missing"]
    openai = FakeJudge(verdict(JudgeProvider.OPENAI, JudgeStatus.PASS))
    groq = FakeJudge(verdict(JudgeProvider.GROQ, JudgeStatus.PASS))

    result = await JudgingService(openai, groq).evaluate(request)

    assert result.deterministic_validation.passed is False
    assert result.openai_verdict is None
    assert (openai.calls, groq.calls) == (0, 0)


@pytest.mark.parametrize(
    ("openai_status", "groq_status", "decision"),
    [
        (JudgeStatus.PASS, JudgeStatus.PASS, "FINALIZE_READ_ONLY"),
        (JudgeStatus.PASS, JudgeStatus.FAIL, "NEEDS_REPAIR"),
        (JudgeStatus.FAIL, JudgeStatus.FAIL, "NEEDS_REPAIR"),
        (JudgeStatus.TIMEOUT, JudgeStatus.PASS, "AWAITING_HUMAN"),
        (JudgeStatus.TIMEOUT, JudgeStatus.ERROR, "BLOCKED"),
    ],
)
def test_aggregator_applies_consensus_policy(
    openai_status: JudgeStatus, groq_status: JudgeStatus, decision: str
) -> None:
    aggregate = aggregate_verdicts(
        verdict(JudgeProvider.OPENAI, openai_status),
        verdict(JudgeProvider.GROQ, groq_status),
    )

    assert aggregate.decision == decision


def test_aggregator_rejects_a_nominal_pass_below_the_required_thresholds() -> None:
    weak_pass = verdict(JudgeProvider.OPENAI, JudgeStatus.PASS)
    weak_pass.scores.grounding = 3

    aggregate = aggregate_verdicts(
        weak_pass, verdict(JudgeProvider.GROQ, JudgeStatus.PASS)
    )

    assert aggregate.decision == "NEEDS_REPAIR"


def test_aggregator_stops_after_two_unsuccessful_repair_cycles() -> None:
    aggregate = aggregate_verdicts(
        verdict(JudgeProvider.OPENAI, JudgeStatus.FAIL),
        verdict(JudgeProvider.GROQ, JudgeStatus.FAIL),
        repair_cycles=2,
    )

    assert aggregate.decision == "AWAITING_HUMAN"


def test_judging_endpoint_uses_injected_independent_judges() -> None:
    service = JudgingService(
        FakeJudge(verdict(JudgeProvider.OPENAI, JudgeStatus.PASS)),
        FakeJudge(verdict(JudgeProvider.GROQ, JudgeStatus.PASS)),
    )
    app.dependency_overrides[get_judging_service] = lambda: service
    try:
        response = TestClient(app).post(
            "/api/v1/judges/evaluate", json=judging_request().model_dump(mode="json")
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["result"]["aggregate_decision"]["decision"] == "FINALIZE_READ_ONLY"
    assert response.json()["run_id"]


def test_judge_packet_bounds_raw_metadata_and_is_shared_by_both_judges() -> None:
    request = judging_request()
    packet = _judge_packet(request)

    assert packet["impacts"][0]["evidence_ids"] == ["ev_lineage_001"]
    assert "raw_reference" not in packet["evidence_index"][0]
    assert packet["remediation_plan"]["execution_status"] == "NOT_EXECUTED"


def test_groq_strict_schema_requires_all_verdict_fields() -> None:
    schema = _verdict_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "verdict", "scores", "critical_errors", "non_critical_issues", "repair_instructions", "audit_rationale", "confidence"
    }
