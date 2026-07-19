import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.datahub.mcp_client import get_datahub_client
from app.domain.contracts import ChangeRequest
from app.main import app
from app.services.impact_analysis import ImpactAnalysisService

SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
DOWNSTREAM_URN = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"


class FakeDataHubMcpClient:
    async def list_schema_fields(self, urn: str) -> dict:
        assert urn == SOURCE_URN
        return {
            "structuredContent": {
                "totalFields": 2,
                "fields": [
                    {"fieldPath": "customer_status"},
                    {"fieldPath": "order_id"},
                ],
            }
        }

    async def get_lineage(self, urn: str, direction: str, max_hops: int) -> dict:
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
