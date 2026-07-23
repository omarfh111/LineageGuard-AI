import pytest

from app.core.config import Settings
from app.services.catalog_cache import CatalogCache


SOURCE = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"
TARGET = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.orders_dashboard,PROD)"


def entity(urn: str, name: str, platform: str) -> dict:
    return {
        "urn": urn,
        "type": "DATASET",
        "properties": {"name": name},
        "platform": {"urn": platform},
    }


class CacheClient:
    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        assert query == "*"
        if offset:
            return {"structuredContent": {"searchResults": []}}
        return {"structuredContent": {"searchResults": [{"entity": entity(SOURCE, "orders", "urn:li:dataPlatform:dbt")}]}}

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        assert (urn, direction, max_hops) == (SOURCE, "DOWNSTREAM", 1)
        return {"structuredContent": {"downstreams": {"total": 1, "searchResults": [{"degree": 1, "entity": entity(TARGET, "orders_dashboard", "urn:li:dataPlatform:tableau")}]}}}


@pytest.mark.asyncio
async def test_server_catalog_cache_loads_once_and_attaches_local_actions() -> None:
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20, catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=CacheClient)  # type: ignore[arg-type]

    await cache._refresh("test_load")
    await cache.record_action(SOURCE, "IMPACT_ANALYSIS_COMPLETED", "Read-only impact analysis completed.")
    snapshot = await cache.snapshot()

    assert snapshot.status.state == "READY"
    assert {node.urn for node in snapshot.graph.nodes} == {SOURCE, TARGET}
    assert snapshot.graph.edges[0].target_urn == TARGET
    source = next(node for node in snapshot.graph.nodes if node.urn == SOURCE)
    assert source.recent_actions[0].action == "IMPACT_ANALYSIS_COMPLETED"
