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
        # Search result labels and platform decorations can change without the
        # catalog changing.  Only the stable DataHub URNs decide whether a
        # lineage traversal is needed.
        self._root_identity: frozenset[str] = frozenset()
        self._pending_root_identity: frozenset[str] | None = None
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
        """Compare only root assets, never the lineage-enriched display graph."""

        try:
            fresh = await self._load_catalog_nodes()
        except (DataHubConfigurationError, OSError, TimeoutError):
            return False
        identity = _root_identity(fresh)
        if identity == self._root_identity:
            self._pending_root_identity = None
            return False

        # A second, identical observation prevents a transient DataHub search
        # ordering/indexing fluctuation from triggering a 1k+ lineage scan.
        if identity != self._pending_root_identity:
            self._pending_root_identity = identity
            return False
        self._pending_root_identity = None
        return True

    async def _refresh(self, reason: str) -> None:
        try:
            async with self._lock:
                had_graph = bool(self._graph.nodes)
                self._status = CatalogCacheStatus(
                    state=CatalogCacheState.RUNNING,
                    loaded_assets=len(self._graph.nodes),
                    loaded_edges=len(self._graph.edges),
                    message=(
                        "Refreshing the DataHub 3D catalog in the background; the existing graph is preserved."
                        if had_graph else "Refreshing the bounded DataHub 3D catalog in the background."
                    ),
                    last_updated_at=self._status.last_updated_at,
                    refresh_reason=reason,
                )
            roots = await self._load_catalog_nodes()
            if not had_graph:
                async with self._lock:
                    # Initial startup has no graph to preserve, so publish roots
                    # promptly while lineage batches are discovered.
                    self._graph = CatalogGraph(nodes=roots, edges=[], query="*", max_hops=1)
                    self._status = self._status.model_copy(
                        update={
                            # The complete root catalog is immediately usable
                            # in 3D.  Relationship enrichment continues in the
                            # background and must not present the UI as stuck.
                            "state": CatalogCacheState.READY,
                            "loaded_assets": len(roots),
                            "message": "Catalog assets are ready; enriching observed lineage relationships in the background.",
                        }
                    )
            graph = await self._load_lineage_graph(roots, publish_progress=not had_graph)
            now = datetime.now(UTC)
            async with self._lock:
                self._graph = graph
                self._root_identity = _root_identity(roots)
                self._pending_root_identity = None
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
        page_size = 50
        pages = [
            ("*", min(page_size, self._settings.catalog_max_assets - offset), offset)
            for offset in range(0, self._settings.catalog_max_assets, page_size)
        ]
        search_many = getattr(client, "search_many", None)
        if callable(search_many):
            results = await search_many(pages)
            for result in results:
                for node in catalog_from_search(result, "*").nodes:
                    nodes.setdefault(node.urn, node)
        else:
            for query, count, offset in pages:
                result = await client.search(query, num_results=count, offset=offset)
                graph = catalog_from_search(result, "*")
                if not graph.nodes:
                    break
                for node in graph.nodes:
                    nodes.setdefault(node.urn, node)
                if len(graph.nodes) < count:
                    break
        return list(nodes.values())

    async def _load_lineage_graph(self, roots: list[CatalogNode], *, publish_progress: bool) -> CatalogGraph:
        client = self._client_factory()
        async def fetch(root: CatalogNode) -> CatalogGraph | None:
            try:
                result = await client.get_lineage(root.urn, "DOWNSTREAM", 1, max_results=100)
                return catalog_from_lineage(result, root.urn, "DOWNSTREAM", 1)
            except (DataHubConfigurationError, OSError, TimeoutError):
                return None

        nodes: dict[str, CatalogNode] = {node.urn: node for node in roots}
        edges: dict[tuple[str, str, str], CatalogEdge] = {}
        for start in range(0, len(roots), 50):
            batch = roots[start : start + 50]
            lineage_many = getattr(client, "get_lineage_many", None)
            if callable(lineage_many):
                try:
                    results = await lineage_many(
                        [(root.urn, "DOWNSTREAM", 1, 100) for root in batch]
                    )
                    projections = [
                        catalog_from_lineage(result, root.urn, "DOWNSTREAM", 1)
                        for root, result in zip(batch, results, strict=True)
                    ]
                except (DataHubConfigurationError, OSError, TimeoutError):
                    projections = [None] * len(batch)
            else:
                semaphore = asyncio.Semaphore(self._settings.catalog_lineage_concurrency)

                async def limited_fetch(root: CatalogNode) -> CatalogGraph | None:
                    async with semaphore:
                        return await fetch(root)

                projections = await asyncio.gather(*(limited_fetch(root) for root in batch))
            for projection in projections:
                if projection is None:
                    continue
                for node in projection.nodes:
                    if len(nodes) < self._settings.catalog_max_assets or node.urn in nodes:
                        nodes.setdefault(node.urn, node)
                for edge in projection.edges:
                    if len(edges) < self._settings.catalog_max_edges:
                        edges.setdefault((edge.source_urn, edge.target_urn, edge.direction), edge)
            if publish_progress:
                async with self._lock:
                    self._graph = CatalogGraph(
                        nodes=list(nodes.values())[: self._settings.catalog_max_assets],
                        edges=list(edges.values())[: self._settings.catalog_max_edges],
                        query="*",
                        max_hops=1,
                        truncated=len(nodes) > self._settings.catalog_max_assets
                        or len(edges) > self._settings.catalog_max_edges,
                    )
            async with self._lock:
                self._status = self._status.model_copy(
                    update={
                        "loaded_assets": len(nodes) if publish_progress else len(self._graph.nodes),
                        "loaded_edges": len(edges) if publish_progress else len(self._graph.edges),
                        "message": (
                            f"Loading lineage for {min(start + 50, len(roots))}/{len(roots)} catalog assets in the background."
                            if publish_progress else
                            f"Refreshing lineage in the background; existing graph remains available ({min(start + 50, len(roots))}/{len(roots)} assets checked)."
                        ),
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


def _root_identity(nodes: list[CatalogNode]) -> frozenset[str]:
    """Fingerprint root membership only; display metadata is not freshness."""

    return frozenset(node.urn for node in nodes)
