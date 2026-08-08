import asyncio

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
    async def list_schema_fields(self, urn: str) -> dict:
        assert urn == SOURCE
        return {
            "structuredContent": {
                "fields": [{"fieldPath": "order_id", "type": "NUMBER"}]
            }
        }


class MutableCacheClient(CacheClient):
    def __init__(self) -> None:
        self.schema_type = "NUMBER"
        self.lineage_target = TARGET
        self.hang_search = False
        self.fail_lineage = False

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        if self.hang_search:
            await asyncio.Event().wait()
        return await super().search(query, num_results, offset)

    async def list_schema_fields(self, urn: str) -> dict:
        return {
            "structuredContent": {
                "fields": [{"fieldPath": "order_id", "type": self.schema_type}]
            }
        }

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        if self.fail_lineage:
            raise OSError("temporary lineage failure")
        return {
            "structuredContent": {
                "downstreams": {
                    "total": 1,
                    "searchResults": [
                        {
                            "degree": 1,
                            "entity": entity(
                                self.lineage_target,
                                "downstream",
                                "urn:li:dataPlatform:tableau",
                            ),
                        }
                    ],
                }
            }
        }


class RecoveringCacheClient(CacheClient):
    def __init__(self) -> None:
        self.search_attempts = 0

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        self.search_attempts += 1
        if self.search_attempts == 1:
            await asyncio.Event().wait()
        return await super().search(query, num_results, offset)


class PartialBatchCacheClient(CacheClient):
    async def get_lineage_many(self, requests: list[tuple[str, str, int, int]]) -> list[dict]:
        """Simulate an MCP batch truncated by a provider response budget."""

        return []


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


@pytest.mark.asyncio
async def test_incomplete_mcp_batch_retries_roots_individually() -> None:
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20, catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=PartialBatchCacheClient)  # type: ignore[arg-type]

    await cache._refresh("partial_batch")
    snapshot = await cache.snapshot()

    assert snapshot.status.state == "READY"
    assert snapshot.graph.edges[0].target_urn == TARGET


@pytest.mark.asyncio
async def test_cache_identity_uses_roots_not_enriched_lineage_nodes() -> None:
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20, catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=CacheClient)  # type: ignore[arg-type]

    await cache._refresh("initial")

    assert not await cache._catalog_identity_changed()


@pytest.mark.asyncio
async def test_cache_requires_two_identical_changed_polls_before_refreshing() -> None:
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20, catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=CacheClient)  # type: ignore[arg-type]
    await cache._refresh("initial")

    # Simulate an external root change. A single inconsistent search response
    # must not trigger another complete lineage traversal.
    cache._root_identity = frozenset({"urn:li:dataset:(urn:li:dataPlatform:dbt,old.orders,PROD)"})
    assert not await cache._catalog_identity_changed()
    assert await cache._catalog_identity_changed()


@pytest.mark.asyncio
async def test_cache_detects_a_schema_change_without_changing_root_urns() -> None:
    client = MutableCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20, catalog_change_probe_assets=1,
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]
    await cache._refresh("initial")

    assert not await cache._catalog_identity_changed()
    client.schema_type = "TEXT"

    assert await cache._catalog_identity_changed()
    assert cache._detected_change is not None
    assert cache._detected_change.startswith("schema:")


@pytest.mark.asyncio
async def test_cache_detects_a_direct_lineage_change() -> None:
    client = MutableCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20, catalog_change_probe_assets=1,
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]
    await cache._refresh("initial")
    client.lineage_target = "urn:li:dataset:(urn:li:dataPlatform:tableau,shop.new_dashboard,PROD)"

    assert await cache._catalog_identity_changed()
    assert cache._detected_change is not None
    assert cache._detected_change.startswith("lineage:")


@pytest.mark.asyncio
async def test_refresh_watchdog_preserves_graph_and_reports_failure() -> None:
    client = MutableCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20, catalog_refresh_timeout_seconds=0.03,  # type: ignore[arg-type]
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]
    await cache._refresh("initial")
    original = await cache.snapshot()
    client.hang_search = True

    await cache._guarded_refresh("stuck_refresh")
    recovered = await cache.snapshot()

    assert recovered.status.state == "STALE"
    assert recovered.status.refresh_in_progress is False
    assert recovered.status.consecutive_failures == 1
    assert "watchdog" in (recovered.status.last_error or "")
    assert recovered.graph == original.graph


@pytest.mark.asyncio
async def test_incomplete_lineage_refresh_never_replaces_a_good_graph() -> None:
    client = MutableCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]
    await cache._refresh("initial")
    original = await cache.snapshot()
    client.fail_lineage = True

    await cache._guarded_refresh("partial_failure")
    failed = await cache.snapshot()

    assert failed.status.state == "STALE"
    assert failed.status.consecutive_failures == 1
    assert failed.graph == original.graph


@pytest.mark.asyncio
async def test_guarded_refresh_recovers_after_an_unexpected_provider_error() -> None:
    client = MutableCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20,
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]
    client.fail_lineage = True
    await cache._guarded_refresh("first_attempt")
    # Root assets were published before lineage failed, so the usable partial
    # startup view is marked STALE rather than discarded as FAILED.
    assert (await cache.snapshot()).status.state == "STALE"

    client.fail_lineage = False
    await cache._guarded_refresh("automatic_retry")
    snapshot = await cache.snapshot()

    assert snapshot.status.state == "READY"
    assert snapshot.status.consecutive_failures == 0
    assert snapshot.status.generation == 1


@pytest.mark.asyncio
async def test_background_worker_does_not_loop_after_watchdog_timeout() -> None:
    client = RecoveringCacheClient()
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20, catalog_refresh_seconds=0.03,  # type: ignore[arg-type]
        catalog_refresh_timeout_seconds=0.02,  # type: ignore[arg-type]
    )
    cache = CatalogCache(settings, client_factory=lambda: client)  # type: ignore[arg-type]

    await cache._start_worker("watchdog_test")
    await asyncio.sleep(0.12)
    snapshot = await cache.snapshot()
    await cache.stop()

    assert client.search_attempts == 1
    assert snapshot.status.state == "FAILED"
    assert snapshot.status.consecutive_failures == 1
    assert snapshot.status.generation == 0


@pytest.mark.asyncio
async def test_unchanged_polls_never_start_another_full_refresh() -> None:
    settings = Settings(
        app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
        catalog_max_edges=20, catalog_refresh_seconds=0.02,  # type: ignore[arg-type]
        catalog_refresh_timeout_seconds=0.5,  # type: ignore[arg-type]
        catalog_change_probe_assets=1,
    )
    cache = CatalogCache(settings, client_factory=CacheClient)  # type: ignore[arg-type]

    await cache._start_worker("unchanged_poll_test")
    deadline = asyncio.get_running_loop().time() + 0.5
    while (await cache.snapshot()).status.generation < 1:
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("initial catalog generation did not complete")
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.12)
    snapshot = await cache.snapshot()
    await cache.stop()

    assert snapshot.status.generation == 1
    assert snapshot.status.refresh_in_progress is False
    assert snapshot.status.last_checked_at is not None


@pytest.mark.asyncio
async def test_change_watch_timeout_uses_backoff_without_marking_ready_graph_failed() -> None:
    cache = CatalogCache(
        Settings(
            app_env="test", database_url="sqlite:///:memory:", datahub_gms_url="http://localhost:8080",
            datahub_gms_token=None, catalog_autoload=False, catalog_max_assets=20,
            catalog_max_edges=20, catalog_refresh_seconds=1,
        ),
        client_factory=CacheClient,  # type: ignore[arg-type]
    )
    await cache._refresh("initial")
    attempts = 0

    async def timed_out_probe() -> bool:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("transient DataHub watch timeout")

    cache._catalog_identity_changed = timed_out_probe  # type: ignore[method-assign]
    assert not await cache._guarded_change_check()
    first = await cache.snapshot()
    assert first.status.state == "READY"
    assert first.status.last_error is None
    assert attempts == 1

    # The backoff suppresses an immediate noisy retry.
    assert not await cache._guarded_change_check()
    assert attempts == 1
