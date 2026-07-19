from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.domain.contracts import (
    ChangeRequest,
    ClaimType,
    EvidenceBundle,
    EvidenceItem,
    ImpactItem,
    ImpactReport,
    RiskAssessment,
    RiskComponents,
)
from app.main import app
from app.services.remediation_planner import DeterministicRemediationPlanner

SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
DOWNSTREAM_URN = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"


def impact_report(change_type: str, **overrides: object) -> ImpactReport:
    request_data: dict[str, object] = {
        "asset_urn": SOURCE_URN,
        "change_type": change_type,
        "column_name": "customer_status",
        "new_value": "fulfillment_status" if change_type == "RENAME_COLUMN" else None,
        "reason": "A governed source field replaces this contract.",
        "environment": "DEMO",
    }
    request_data.update(overrides)
    request = ChangeRequest(**request_data)
    return ImpactReport(
        request=request,
        evidence_bundle=EvidenceBundle(
            source_asset_urn=SOURCE_URN,
            items=[
                EvidenceItem(
                    evidence_id="ev_001",
                    tool="get_lineage",
                    asset_urn=DOWNSTREAM_URN,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={},
                    retrieved_at=datetime.now(UTC),
                )
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
                evidence_ids=["ev_001"],
            )
        ],
        missing_metadata=[],
        risk_assessment=RiskAssessment(
            score=70,
            level="HIGH",
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


def test_drop_column_plan_never_executes_a_destructive_change() -> None:
    plan = DeterministicRemediationPlanner().plan(impact_report("DROP_COLUMN"))

    assert plan.execution_status == "NOT_EXECUTED"
    assert plan.rollback_plan.execution_status == "NOT_EXECUTED"
    assert plan.backward_compatible is False
    assert plan.deprecation_period is not None
    assert any("human approval" in step.action.lower() for step in plan.migration_steps)


def test_rename_plan_keeps_a_compatibility_path() -> None:
    plan = DeterministicRemediationPlanner().plan(impact_report("RENAME_COLUMN"))

    assert plan.backward_compatible is True
    assert plan.forward_compatible is True
    assert "compatibility alias" in plan.migration_steps[1].action


def test_add_column_plan_is_backward_and_forward_compatible() -> None:
    plan = DeterministicRemediationPlanner().plan(
        impact_report("ADD_COLUMN", column_name="fulfillment_status", column_nullable=True)
    )

    assert (plan.backward_compatible, plan.forward_compatible) == (True, True)


def test_remediation_endpoint_returns_a_non_executing_plan() -> None:
    report = impact_report("DROP_COLUMN")
    response = TestClient(app).post(
        "/api/v1/remediations/plan", json=report.model_dump(mode="json")
    )

    assert response.status_code == 200
    assert response.json()["execution_status"] == "NOT_EXECUTED"
