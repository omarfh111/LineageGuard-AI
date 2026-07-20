from fastapi.testclient import TestClient

from app.datahub.mcp_client import get_datahub_client
from app.main import app
from app.services.catalog_graph import catalog_from_lineage, catalog_from_search, catalog_snapshot

SOURCE = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
TARGET = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"


def entity(urn: str, name: str, platform: str = "urn:li:dataPlatform:dbt") -> dict:
    return {
        "urn": urn,
        "type": "DATASET",
        "properties": {"name": name},
        "platform": {"urn": platform},
        "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:owner"}}]},
    }


def test_catalog_search_projects_safe_asset_nodes_only() -> None:
    graph = catalog_from_search(
        {"structuredContent": {"searchResults": [{"entity": entity(SOURCE, "orders")}] }},
        "orders",
    )

    assert graph.query == "orders"
    assert graph.edges == []
    assert graph.nodes[0].label == "orders"
    assert graph.nodes[0].owner_urns == ["urn:li:corpuser:owner"]


def test_catalog_lineage_preserves_direction_and_hop_count() -> None:
    graph = catalog_from_lineage(
        {"structuredContent": {"downstreams": {"total": 1, "searchResults": [{"degree": 2, "entity": entity(TARGET, "orders dashboard", "urn:li:dataPlatform:tableau")}]} }},
        SOURCE,
        "DOWNSTREAM",
        3,
    )

    assert {node.urn for node in graph.nodes} == {SOURCE, TARGET}
    assert graph.edges[0].source_urn == SOURCE
    assert graph.edges[0].target_urn == TARGET
    assert graph.edges[0].hops == 2


class CatalogClient:
    async def search(self, query: str) -> dict:
        return {"structuredContent": {"searchResults": [{"entity": entity(SOURCE, query)}]}}

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        return {"structuredContent": {"downstreams": {"total": 1, "searchResults": [{"degree": 1, "entity": entity(TARGET, "orders dashboard")} ]}}}


def test_catalog_routes_are_read_only_projections() -> None:
    app.dependency_overrides[get_datahub_client] = lambda: CatalogClient()
    try:
        client = TestClient(app)
        search = client.get("/api/v1/datahub/catalog/search", params={"query": "orders"})
        expand = client.get("/api/v1/datahub/catalog/expand", params={"asset_urn": SOURCE})
    finally:
        app.dependency_overrides.clear()

    assert search.status_code == 200
    assert search.json()["nodes"][0]["label"] == "orders"
    assert expand.status_code == 200
    assert expand.json()["edges"][0]["target_urn"] == TARGET


class SnapshotClient:
    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        return {"structuredContent": {"searchResults": [{"entity": entity(SOURCE, "orders")}]}}

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        return {"structuredContent": {"downstreams": {"total": 1, "searchResults": [{"degree": 1, "entity": entity(TARGET, "orders dashboard")} ]}}}


def test_catalog_snapshot_collects_only_observed_bounded_links() -> None:
    import asyncio

    graph = asyncio.run(catalog_snapshot(SnapshotClient(), max_assets=10, max_edges=10))

    assert {node.urn for node in graph.nodes} == {SOURCE, TARGET}
    assert graph.edges[0].source_urn == SOURCE
