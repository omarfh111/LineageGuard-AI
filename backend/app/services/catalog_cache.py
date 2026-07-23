"""Server-owned, non-blocking cache for the complete bounded 3D catalog.

The browser never starts the expensive catalog traversal.  The API does it once
at boot, keeps the graph in memory while the server runs, polls cheaply for
catalog identity changes, and refreshes immediately after LineageGuard records
an in-app DataHub action.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.config import Settings, get_settings
from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient
from app.domain.contracts import (
    CatalogAction,
    CatalogCacheSnapshot,
    CatalogCacheState,
    CatalogCacheStatus,
    CatalogEdge,
    CatalogGraph,
    CatalogNode,
)
from app.services.catalog_graph import catalog_from_lineage, catalog_from_search


CatalogClientFactory = Callable[[], DataHubMcpClient]


class CatalogCache:
    """One bounded cache per API process with auditable freshness state."""

    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: CatalogClientFactory | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_factory = client_factory or (lambda: DataHubMcpClient(get_settings()))
        self._graph = CatalogGraph(nodes=[], edges=[], query="*", truncated=False)
        self._status = CatalogCacheStatus()
        self._actions: dict[str, list[CatalogAction]] = {}
        self._task: asyncio.Task[None] | None = None
        self._refresh_event = asyncio.Event()
        self._refresh_reasons: list[str] = []
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Schedule background loading; never delay API readiness."""

        if not self._settings.catalog_autoload or (self._task and not self._task.done()):
            return
        async with self._lock:
            self._status = CatalogCacheStatus(
                state=CatalogCacheState.RUNNING,
                message="Loading the DataHub 3D catalog in the background.",
                refresh_reason="server_start",
            )
        self._task = asyncio.create_task(self._run(), name="lineageguard-catalog-cache")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def snapshot(self) -> CatalogCacheSnapshot:
        async with self._lock:
            nodes = [
                node.model_copy(update={"recent_actions": list(self._actions.get(node.urn, []))})
                for node in self._graph.nodes
            ]
            return CatalogCacheSnapshot(
                status=self._status.model_copy(),
                graph=self._graph.model_copy(update={"nodes": nodes}),
            )

    async def request_refresh(self, reason: str) -> CatalogCacheStatus:
        """Coalesce explicit refresh requests rather than spawning duplicate scans."""

        async with self._lock:
            self._refresh_reasons.append(reason[:160])
            if self._status.state is CatalogCacheState.READY:
                self._status = self._status.model_copy(
                    update={
                        "state": CatalogCacheState.STALE,
                        "message": "Catalog refresh requested; the current graph remains available.",
                        "refresh_reason": reason[:160],
                    }
                )
        self._refresh_event.set()
        return (await self.snapshot()).status

    async def record_action(self, asset_urn: str, action: str, detail: str) -> None:
        """Attach a local, public activity record to an asset hover card."""

        event = CatalogAction(
            timestamp=datetime.now(UTC), action=action[:80], detail=detail[:500]
        )
        async with self._lock:
            history = self._actions.setdefault(asset_urn, [])
            history.insert(0, event)
            del history[8:]

    async def merge_observed_graph(
        self, graph: CatalogGraph, action_urn: str | None = None, action: str | None = None
    ) -> None:
        """Immediately reflect a bounded read/action without waiting for polling."""

        async with self._lock:
            nodes = {node.urn: node for node in self._graph.nodes}
            nodes.update({node.urn: node for node in graph.nodes})
            edges = {
                (edge.source_urn, edge.target_urn, edge.direction): edge
                for edge in self._graph.edges
            }
            for edge in graph.edges:
                if len(edges) >= self._settings.catalog_max_edges:
                    break
                edges.setdefault((edge.source_urn, edge.target_urn, edge.direction), edge)
            self._graph = CatalogGraph(
                nodes=list(nodes.values())[: self._settings.catalog_max_assets],
                edges=list(edges.values())[: self._settings.catalog_max_edges],
                query="*",
                truncated=len(nodes) > self._settings.catalog_max_assets
                or len(edges) > self._settings.catalog_max_edges,
            )
        if action_urn and action:
            await self.record_action(action_urn, action, "Observed through an allowlisted DataHub MCP read.")

    async def _run(self) -> None:
        reason = "server_start"
        while True:
            await self._refresh(reason)
            try:
                await asyncio.wait_for(
                    self._refresh_event.wait(), timeout=self._settings.catalog_refresh_seconds
                )
                self._refresh_event.clear()
                async with self._lock:
                    reason = self._refresh_reasons.pop(0) if self._refresh_reasons else "requested_refresh"
            except TimeoutError:
                reason = "scheduled_catalog_poll"
                if (await self.snapshot()).status.state is CatalogCacheState.FAILED:
                    reason = "retry_after_datahub_unavailable"
                    continue
                if not await self._catalog_identity_changed():
                    continue

    async def _catalog_identity_changed(self) -> bool:
        """Cheaply detect adds/removals/basic metadata edits before a full edge scan."""

        try:
            fresh = await self._load_catalog_nodes()
        except (DataHubConfigurationError, OSError, TimeoutError):
            return False
        async with self._lock:
            current = {(node.urn, node.label, node.entity_type, node.platform_urn) for node in self._graph.nodes}
        observed = {(node.urn, node.label, node.entity_type, node.platform_urn) for node in fresh}
        return observed != current

    async def _refresh(self, reason: str) -> None:
        try:
            async with self._lock:
                self._status = CatalogCacheStatus(
                    state=CatalogCacheState.RUNNING,
                    loaded_assets=len(self._graph.nodes),
                    loaded_edges=len(self._graph.edges),
                    message="Refreshing the bounded DataHub 3D catalog in the background.",
                    refresh_reason=reason,
            )
            roots = await self._load_catalog_nodes()
            async with self._lock:
                # Publish discovered assets immediately. The UI can render the
                # complete catalog while relationship batches are still added.
                self._graph = CatalogGraph(nodes=roots, edges=[], query="*", max_hops=1)
                self._status = self._status.model_copy(
                    update={
                        "loaded_assets": len(roots),
                        "message": "Catalog assets discovered; loading observed lineage relationships in the background.",
                    }
                )
            graph = await self._load_lineage_graph(roots)
            now = datetime.now(UTC)
            async with self._lock:
                self._graph = graph
                self._status = CatalogCacheStatus(
                    state=CatalogCacheState.READY,
                    loaded_assets=len(graph.nodes),
                    loaded_edges=len(graph.edges),
                    message="Server-side 3D catalog cache is ready and stays available to every browser.",
                    last_updated_at=now,
                    refresh_reason=reason,
                )
        except (DataHubConfigurationError, OSError, TimeoutError) as error:
            async with self._lock:
                state = CatalogCacheState.STALE if self._graph.nodes else CatalogCacheState.FAILED
                self._status = CatalogCacheStatus(
                    state=state,
                    loaded_assets=len(self._graph.nodes),
                    loaded_edges=len(self._graph.edges),
                    message=f"Catalog cache refresh failed: {type(error).__name__}. Existing graph remains available when present.",
                    last_updated_at=self._status.last_updated_at,
                    refresh_reason=reason,
                )

    async def _load_catalog_nodes(self) -> list[CatalogNode]:
        client = self._client_factory()
        nodes: dict[str, CatalogNode] = {}
        offset = 0
        while len(nodes) < self._settings.catalog_max_assets:
            page_size = min(50, self._settings.catalog_max_assets - len(nodes))
            result = await client.search("*", num_results=page_size, offset=offset)
            graph = catalog_from_search(result, "*")
            if not graph.nodes:
                break
            for node in graph.nodes:
                nodes.setdefault(node.urn, node)
            offset += page_size
            if len(graph.nodes) < page_size:
                break
        return list(nodes.values())

    async def _load_lineage_graph(self, roots: list[CatalogNode]) -> CatalogGraph:
        client = self._client_factory()
        semaphore = asyncio.Semaphore(self._settings.catalog_lineage_concurrency)

        async def fetch(root: CatalogNode) -> CatalogGraph | None:
            try:
                async with semaphore:
                    result = await client.get_lineage(
                        root.urn, "DOWNSTREAM", 1, max_results=100
                    )
                return catalog_from_lineage(result, root.urn, "DOWNSTREAM", 1)
            except (DataHubConfigurationError, OSError, TimeoutError):
                return None

        nodes: dict[str, CatalogNode] = {node.urn: node for node in roots}
        edges: dict[tuple[str, str, str], CatalogEdge] = {}
        for start in range(0, len(roots), 50):
            projections = await asyncio.gather(*(fetch(root) for root in roots[start : start + 50]))
            for projection in projections:
                if projection is None:
                    continue
                for node in projection.nodes:
                    if len(nodes) < self._settings.catalog_max_assets or node.urn in nodes:
                        nodes.setdefault(node.urn, node)
                for edge in projection.edges:
                    if len(edges) < self._settings.catalog_max_edges:
                        edges.setdefault((edge.source_urn, edge.target_urn, edge.direction), edge)
            async with self._lock:
                self._graph = CatalogGraph(
                    nodes=list(nodes.values())[: self._settings.catalog_max_assets],
                    edges=list(edges.values())[: self._settings.catalog_max_edges],
                    query="*",
                    max_hops=1,
                    truncated=len(nodes) > self._settings.catalog_max_assets
                    or len(edges) > self._settings.catalog_max_edges,
                )
                self._status = self._status.model_copy(
                    update={
                        "loaded_assets": len(nodes),
                        "loaded_edges": len(edges),
                        "message": f"Loading lineage for {min(start + 50, len(roots))}/{len(roots)} catalog assets in the background.",
                    }
                )
        return CatalogGraph(
            nodes=list(nodes.values())[: self._settings.catalog_max_assets],
            edges=list(edges.values())[: self._settings.catalog_max_edges],
            query="*",
            max_hops=1,
            truncated=len(nodes) > self._settings.catalog_max_assets
            or len(edges) > self._settings.catalog_max_edges,
        )


catalog_cache = CatalogCache()
