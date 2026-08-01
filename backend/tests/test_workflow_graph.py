import pytest
from fastapi.testclient import TestClient

from app.datahub.mcp_client import get_datahub_client
from app.domain.contracts import ChangeRequest
from app.main import app
from app.services.workflow_graph import LineageGuardWorkflow
from test_impact_analysis import FakeDataHubMcpClient, request_payload


@pytest.mark.asyncio
async def test_langgraph_analysis_path_returns_plan_and_safe_visualization() -> None:
    execution = await LineageGuardWorkflow(
        client=FakeDataHubMcpClient()
    ).analyze(ChangeRequest.model_validate(request_payload()))

    statuses = {node.id: node.status for node in execution.graph.nodes}
    assert execution.analysis_run_id
    assert execution.impact_report.blast_radius == 1
    assert execution.remediation_plan.execution_status == "NOT_EXECUTED"
    assert statuses["request"] == "COMPLETED"
    assert statuses["metadata"] == "COMPLETED"
    assert statuses["impact"] == "COMPLETED"
    assert statuses["plan"] == "COMPLETED"
    assert not execution.graph.tracing_enabled
    assert all("key" not in node.model_dump_json().lower() for node in execution.graph.nodes)


def test_workflow_endpoint_uses_the_read_only_langgraph_path() -> None:
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).post("/api/v1/workflows/analyze", json=request_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_run_id"]
    assert body["remediation_plan"]["execution_status"] == "NOT_EXECUTED"
    assert {node["id"] for node in body["graph"]["nodes"]} == {
        "request", "metadata", "impact", "plan", "critic", "judges", "hitl"
    }

    restored = TestClient(app).get(
        f"/api/v1/workflows/analysis/{body['analysis_run_id']}"
    )
    assert restored.status_code == 200
    restored_body = restored.json()
    assert restored_body["impact_report"] == body["impact_report"]
    assert restored_body["remediation_plan"] == body["remediation_plan"]
    assert {
        node["id"]: node["status"] for node in restored_body["graph"]["nodes"]
    }["plan"] == "COMPLETED"


def test_workflow_restore_rejects_unknown_and_malformed_run_ids() -> None:
    client = TestClient(app)
    unknown = client.get(
        "/api/v1/workflows/analysis/00000000-0000-0000-0000-000000000000"
    )
    malformed = client.get("/api/v1/workflows/analysis/not-a-run-id")

    assert unknown.status_code == 404
    assert malformed.status_code == 422
