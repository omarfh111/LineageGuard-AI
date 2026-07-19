from fastapi.testclient import TestClient

from app.datahub.mcp_client import get_datahub_client
from app.main import app


class FakeDataHubMcpClient:
    async def search(self, query: str) -> dict:
        return {"content": [{"type": "text", "text": query}]}

    async def list_schema_fields(self, urn: str) -> dict:
        return {"content": [{"type": "text", "text": urn}]}

    async def get_lineage(self, urn: str, direction: str, max_hops: int) -> dict:
        return {
            "content": [{"type": "text", "text": urn}],
            "metadata": {"direction": direction, "max_hops": max_hops},
        }


def test_search_proxies_an_allowlisted_mcp_read_tool() -> None:
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).get("/api/v1/datahub/search", params={"query": "orders"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["tool"] == "search"
    assert response.json()["result"]["content"][0]["text"] == "orders"


def test_lineage_caps_hops_and_returns_read_result() -> None:
    app.dependency_overrides[get_datahub_client] = lambda: FakeDataHubMcpClient()
    try:
        response = TestClient(app).get(
            "/api/v1/datahub/lineage",
            params={"asset_urn": "urn:li:dataset:orders", "max_hops": 3},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["tool"] == "get_lineage"
    assert response.json()["result"]["metadata"] == {
        "direction": "DOWNSTREAM",
        "max_hops": 3,
    }
