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
)
from app.main import app
from app.services.judging import (
    JudgingService,
    _compact_remediation_plan,
    _judge_packet,
    _safe_provider_error,
    _verdict_json_schema,
    aggregate_verdicts,
    validate_gate_zero,
)
from app.services.remediation_planner import DeterministicRemediationPlanner
from app.services.impact_analysis import (
    calculate_risk_assessment,
    expected_missing_metadata,
)
from app.services.run_store import analysis_store

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
    impacts = [
        ImpactItem(
            asset_urn=DOWNSTREAM_URN,
            asset_type="DATASET",
            lineage_path=[SOURCE_URN, DOWNSTREAM_URN],
            owner_urns=["urn:li:corpuser:owner"],
            platform_urn="urn:li:dataPlatform:tableau",
            criticality="HIGH",
            evidence_ids=["ev_lineage_001"],
        )
    ]
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
                    evidence_id="ev_lineage_summary",
                    tool="get_lineage",
                    asset_urn=SOURCE_URN,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={
                        "source_asset_urn": SOURCE_URN,
                        "returned_assets": 1,
                        "total_downstreams": 1,
                        "direction": "DOWNSTREAM",
                        "max_hops": 3,
                    },
                    retrieved_at=datetime.now(UTC),
                ),
                EvidenceItem(
                    evidence_id="ev_lineage_001",
                    tool="get_lineage",
                    asset_urn=DOWNSTREAM_URN,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={
                        "source_asset_urn": SOURCE_URN,
                        "downstream_asset_urn": DOWNSTREAM_URN,
                        "degree": 1,
                        "owner_urns": ["urn:li:corpuser:owner"],
                        "platform_urn": "urn:li:dataPlatform:tableau",
                        "criticality": "HIGH",
                    },
                    retrieved_at=datetime.now(UTC),
                ),
            ],
        ),
        blast_radius=1,
        impacted_assets=impacts,
        missing_metadata=[],
        risk_assessment=calculate_risk_assessment(request, impacts, []),
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
    request = judging_request()
    analysis_run_id = analysis_store.save(
        request.impact_report, request.remediation_plan
    )
    try:
        response = TestClient(app).post(
            "/api/v1/judges/evaluate",
            json={"analysis_run_id": analysis_run_id, "repair_cycles": 0},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["result"]["aggregate_decision"]["decision"] == "FINALIZE_READ_ONLY"
    assert response.json()["run_id"]


def test_workflow_judge_uses_the_server_owned_analysis_snapshot() -> None:
    service = JudgingService(
        FakeJudge(verdict(JudgeProvider.OPENAI, JudgeStatus.PASS)),
        FakeJudge(verdict(JudgeProvider.GROQ, JudgeStatus.PASS)),
    )
    request = judging_request()
    analysis_run_id = analysis_store.save(
        request.impact_report, request.remediation_plan
    )
    app.dependency_overrides[get_judging_service] = lambda: service
    try:
        response = TestClient(app).post(
            "/api/v1/workflows/judge",
            json={"analysis_run_id": analysis_run_id, "repair_cycles": 0},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert (
        response.json()["judging"]["result"]["aggregate_decision"]["decision"]
        == "FINALIZE_READ_ONLY"
    )


def test_judging_endpoint_rejects_a_client_supplied_report() -> None:
    response = TestClient(app).post(
        "/api/v1/judges/evaluate", json=judging_request().model_dump(mode="json")
    )

    assert response.status_code == 422


def test_judging_endpoint_rejects_an_unknown_analysis_before_provider_setup() -> None:
    response = TestClient(app).post(
        "/api/v1/judges/evaluate",
        json={"analysis_run_id": "unknown-analysis-run", "repair_cycles": 0},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda request: setattr(
                request.impact_report.risk_assessment.components,
                "change_severity",
                1,
            ),
            "Risk components do not match deterministic reconstruction",
        ),
        (
            lambda request: setattr(request.impact_report, "blast_radius", 99),
            "Blast radius does not match the impacted asset count",
        ),
        (
            lambda request: setattr(
                request.impact_report.risk_assessment, "level", "LOW"
            ),
            "Risk level does not match deterministic reconstruction",
        ),
        (
            lambda request: setattr(request.impact_report, "confidence", 0.1),
            "Report confidence does not match metadata uncertainty",
        ),
        (
            lambda request: request.impact_report.missing_metadata.append(
                "fabricated uncertainty"
            ),
            "Missing-metadata facts do not match the observed assets",
        ),
        (
            lambda request: request.impact_report.impacted_assets[
                0
            ].lineage_path.append(SOURCE_URN),
            "Lineage path is inconsistent for impact",
        ),
        (
            lambda request: request.impact_report.evidence_bundle.items[
                2
            ].raw_reference.update(
                {"downstream_asset_urn": SOURCE_URN}
            ),
            "Impact evidence does not prove the target lineage",
        ),
    ],
)
def test_gate_zero_reconstructs_report_facts_instead_of_trusting_fields(
    mutate, expected_error: str
) -> None:
    request = judging_request()
    mutate(request)

    validation = validate_gate_zero(request)

    assert not validation.passed
    assert any(expected_error in error for error in validation.errors)


def test_gate_zero_blocks_internally_consistent_but_fabricated_risk_fields() -> None:
    request = judging_request()
    assessment = request.impact_report.risk_assessment
    assessment.components.change_severity = 0
    assessment.components.blast_radius = 0
    assessment.components.asset_criticality = 0
    assessment.score = 0
    assessment.level = "LOW"
    assessment.explanation = ["Fabricated but internally consistent."]

    validation = validate_gate_zero(request)

    assert not validation.passed
    assert "Risk components do not match deterministic reconstruction" in validation.errors
    assert "Risk score does not match deterministic reconstruction" in validation.errors


def test_gate_zero_rejects_evidence_detached_criticality_even_after_recalculation() -> None:
    request = judging_request()
    report = request.impact_report
    report.impacted_assets[0].criticality = "CRITICAL"
    report.risk_assessment = calculate_risk_assessment(
        report.request, report.impacted_assets, report.missing_metadata
    )
    request.remediation_plan = DeterministicRemediationPlanner().plan(report)

    validation = validate_gate_zero(request)

    assert not validation.passed
    assert any(
        "Impact evidence does not prove the target lineage" in error
        for error in validation.errors
    )


def test_gate_zero_rejects_duplicate_and_unreferenced_evidence() -> None:
    request = judging_request()
    request.impact_report.evidence_bundle.items.append(
        request.impact_report.evidence_bundle.items[0].model_copy(deep=True)
    )

    validation = validate_gate_zero(request)

    assert not validation.passed
    assert "Evidence IDs must be unique" in validation.errors


def test_gate_zero_rejects_plan_targets_outside_the_observed_report() -> None:
    request = judging_request()
    request.remediation_plan.migration_steps[0].affected_asset_urns.append(
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,unobserved.asset,PROD)"
    )

    validation = validate_gate_zero(request)

    assert not validation.passed
    assert any(
        "targets an asset outside the report" in error
        for error in validation.errors
    )


def test_gate_zero_accepts_reconstructed_metadata_uncertainty() -> None:
    request = judging_request()
    report = request.impact_report
    report.impacted_assets[0].owner_urns = []
    report.evidence_bundle.items[2].raw_reference["owner_urns"] = []
    report.missing_metadata = expected_missing_metadata(
        report.impacted_assets, total_downstreams=1
    )
    report.risk_assessment = calculate_risk_assessment(
        report.request, report.impacted_assets, report.missing_metadata
    )
    report.confidence = round(
        1 - report.risk_assessment.components.metadata_uncertainty / 100, 2
    )
    request.remediation_plan = DeterministicRemediationPlanner().plan(report)

    validation = validate_gate_zero(request)

    assert validation.passed, validation.errors


def test_judge_packet_bounds_raw_metadata_and_is_shared_by_both_judges() -> None:
    request = judging_request()
    packet = _judge_packet(request)

    assert packet["impacts"][0]["evidence_ids"] == ["ev_lineage_001"]
    assert "raw_reference" not in packet["evidence_index"][0]
    assert packet["remediation_plan"]["execution_status"] == "NOT_EXECUTED"
    assert packet["remediation_plan"]["target_sets"]
    assert "affected_asset_urns" not in packet["remediation_plan"]["migration_steps"][0]


def test_compact_plan_deduplicates_targets_without_losing_them() -> None:
    request = judging_request()
    compact = _compact_remediation_plan(request)
    scopes = {
        descriptor["scope"] for descriptor in compact["target_sets"].values()
    }

    assert "SOURCE_ASSET" in scopes
    assert "ALL_IMPACTED_ASSETS" in scopes
    assert "SOURCE_AND_ALL_IMPACTED_ASSETS" in scopes
    for step in compact["migration_steps"]:
        assert step["target_count"] == compact["target_sets"][
            step["target_set_id"]
        ]["count"]


def test_judge_packet_does_not_repeat_lineage_paths_or_per_asset_evidence() -> None:
    packet = _judge_packet(judging_request())

    assert "lineage_path" not in packet["impacts"][0]
    assert {item["evidence_id"] for item in packet["evidence_index"]} == {
        "ev_schema_source",
        "ev_lineage_summary",
    }


def test_safe_provider_error_never_exposes_message_or_request_body() -> None:
    class ProviderError(Exception):
        status_code = 429
        body = {
            "error": {
                "code": "rate_limit_exceeded",
                "message": "secret prompt and metadata",
            }
        }

    diagnostic = _safe_provider_error(ProviderError("secret API response"))

    assert diagnostic == "ProviderError status=429 code=rate_limit_exceeded"
    assert "secret" not in diagnostic


def test_groq_strict_schema_requires_all_verdict_fields() -> None:
    schema = _verdict_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "verdict", "scores", "critical_errors", "non_critical_issues", "repair_instructions", "audit_rationale", "confidence"
    }
