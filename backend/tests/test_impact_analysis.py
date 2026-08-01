import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.datahub.mcp_client import get_datahub_client
from app.domain.contracts import ChangeRequest, JudgingRequest
from app.main import app
from app.services.impact_analysis import AnalysisInputError, ImpactAnalysisService
from app.services.judging import validate_gate_zero
from app.services.remediation_planner import DeterministicRemediationPlanner

SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
DOWNSTREAM_URN = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"
INTERMEDIATE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.enriched_orders,PROD)"


class FakeDataHubMcpClient:
    def __init__(self) -> None:
        self.lineage_calls = 0

    async def list_schema_fields(self, urn: str) -> dict:
        assert urn == SOURCE_URN
        return {
            "structuredContent": {
                "totalFields": 2,
                "fields": [
                    {"fieldPath": "customer_status", "nativeDataType": "TEXT"},
                    {"fieldPath": "order_id", "nativeDataType": "NUMBER"},
                ],
            }
        }

    async def get_lineage(self, urn: str, direction: str, max_hops: int) -> dict:
        self.lineage_calls += 1
        assert (urn, direction, max_hops) == (SOURCE_URN, "DOWNSTREAM", 3)
        return {
            "structuredContent": {
                "downstreams": {
                    "searchResults": [
                        {
                            "degree": 1,
                            "entity": {
                                "urn": DOWNSTREAM_URN,
                                "type": "DATASET",
                                "platform": {"urn": "urn:li:dataPlatform:tableau"},
                                "ownership": {
                                    "owners": [
                                        {"owner": {"urn": "urn:li:corpuser:owner"}}
                                    ]
                                },
                                "tags": {
                                    "tags": [
                                        {
                                            "tag": {
                                                "properties": {"name": "Authoritative Source"}
                                            }
                                        }
                                    ]
                                },
                            },
                        }
                    ]
                }
            }
        }


def request_payload() -> dict:
    return {
        "asset_urn": SOURCE_URN,
        "change_type": "DROP_COLUMN",
        "column_name": "customer_status",
        "reason": "Replaced by a governed source field.",
        "environment": "DEMO",
        "lineage_depth": 3,
    }


@pytest.mark.asyncio
async def test_analysis_has_evidence_for_every_impacted_asset() -> None:
    report = await ImpactAnalysisService(FakeDataHubMcpClient()).analyze(
        ChangeRequest.model_validate(request_payload())
    )

    assert report.blast_radius == 1
    assert report.risk_assessment.score == 45
    assert report.risk_assessment.level == "MEDIUM"
    evidence_ids = {item.evidence_id for item in report.evidence_bundle.items}
    assert all(
        set(impact.evidence_ids).issubset(evidence_ids)
        for impact in report.impacted_assets
    )
    assert report.impacted_assets[0].lineage_path == [SOURCE_URN, DOWNSTREAM_URN]


def test_change_request_rejects_drop_without_column_name() -> None:
    payload = request_payload()
    payload.pop("column_name")

    with pytest.raises(ValidationError, match="column_name"):
        ChangeRequest.model_validate(payload)


def test_change_request_rejects_case_only_rename() -> None:
    payload = request_payload() | {
        "change_type": "RENAME_COLUMN",
        "column_name": "customer_status",
        "new_value": " CUSTOMER_STATUS ",
    }

    with pytest.raises(ValidationError, match="rename target"):
        ChangeRequest.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change_type", "column_name", "new_value", "message"),
    [
        ("ADD_COLUMN", "CUSTOMER_STATUS", None, "duplicate"),
        ("RENAME_COLUMN", "customer_status", "ORDER_ID", "already exists"),
        ("CHANGE_COLUMN_TYPE", "customer_status", " text ", "already has type"),
    ],
)
async def test_analysis_rejects_semantically_invalid_schema_changes(
    change_type: str, column_name: str, new_value: str | None, message: str
) -> None:
    payload = request_payload() | {
        "change_type": change_type,
        "column_name": column_name,
    }
    if new_value is not None:
        payload["new_value"] = new_value

    client = FakeDataHubMcpClient()
    with pytest.raises(AnalysisInputError, match=message):
        await ImpactAnalysisService(client).analyze(
            ChangeRequest.model_validate(payload)
        )
    assert client.lineage_calls == 0


@pytest.mark.asyncio
async def test_type_change_records_the_current_type_as_gate_evidence() -> None:
    payload = request_payload() | {
        "change_type": "CHANGE_COLUMN_TYPE",
        "new_value": "VARCHAR(64)",
    }

    report = await ImpactAnalysisService(FakeDataHubMcpClient()).analyze(
        ChangeRequest.model_validate(payload)
    )

    schema = next(
        item for item in report.evidence_bundle.items
        if item.evidence_id == "ev_schema_source"
    )
    assert schema.raw_reference["field_types"]["customer_status"] == "TEXT"


class MultiHopDataHubMcpClient(FakeDataHubMcpClient):
    def __init__(self, path: list[dict] | None = None) -> None:
        super().__init__()
        self.path = path or [
            {"urn": SOURCE_URN, "type": "DATASET"},
            {"urn": "urn:li:query:transform-orders", "type": "QUERY"},
            {"urn": INTERMEDIATE_URN, "type": "DATASET"},
            {"urn": DOWNSTREAM_URN, "type": "DATASET"},
        ]

    async def get_lineage(self, urn: str, direction: str, max_hops: int) -> dict:
        assert (urn, direction, max_hops) == (SOURCE_URN, "DOWNSTREAM", 3)
        response = await super().get_lineage(urn, direction, max_hops)
        response["structuredContent"]["downstreams"]["searchResults"][0]["degree"] = 2
        return response

    async def get_lineage_paths_many(
        self, requests: list[tuple[str, str]]
    ) -> list[dict]:
        assert requests == [(SOURCE_URN, DOWNSTREAM_URN)]
        return [{"structuredContent": {"paths": [{"path": self.path}]}}]


@pytest.mark.asyncio
async def test_multi_hop_impact_uses_the_exact_mcp_path() -> None:
    report = await ImpactAnalysisService(MultiHopDataHubMcpClient()).analyze(
        ChangeRequest.model_validate(request_payload())
    )

    assert report.impacted_assets[0].lineage_path == [
        SOURCE_URN,
        INTERMEDIATE_URN,
        DOWNSTREAM_URN,
    ]
    evidence = next(
        item for item in report.evidence_bundle.items
        if item.evidence_id == "ev_lineage_001"
    )
    assert evidence.tool == "get_lineage_paths_between"
    assert evidence.raw_reference["lineage_path"] == report.impacted_assets[0].lineage_path
    request = JudgingRequest(
        impact_report=report,
        remediation_plan=DeterministicRemediationPlanner().plan(report),
    )
    assert validate_gate_zero(request).passed

    report.impacted_assets[0].lineage_path[1] = "urn:li:dataset:tampered"
    request.remediation_plan = DeterministicRemediationPlanner().plan(report)
    validation = validate_gate_zero(request)
    assert not validation.passed
    assert any("lineage" in error.lower() for error in validation.errors)


@pytest.mark.asyncio
async def test_multi_hop_impact_rejects_an_incomplete_or_cyclic_path() -> None:
    cyclic = [
        {"urn": SOURCE_URN, "type": "DATASET"},
        {"urn": SOURCE_URN, "type": "DATASET"},
        {"urn": DOWNSTREAM_URN, "type": "DATASET"},
    ]

    with pytest.raises(AnalysisInputError, match="No exact MCP lineage path"):
        await ImpactAnalysisService(MultiHopDataHubMcpClient(cyclic)).analyze(
            ChangeRequest.model_validate(request_payload())
        )


def test_impact_endpoint_returns_a_structured_read_only_report() -> None:
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).post("/api/v1/analyses/impact", json=request_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["risk_assessment"]["score"] == 45
    assert body["impacted_assets"][0]["evidence_ids"] == ["ev_lineage_001"]
