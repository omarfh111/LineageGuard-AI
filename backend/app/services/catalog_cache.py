"""Server-owned, non-blocking cache for the complete bounded 3D catalog.

The browser never starts the expensive catalog traversal.  The API does it once
at boot, keeps the graph in memory while the server runs, polls cheaply for
catalog identity changes, and refreshes immediately after LineageGuard records
an in-app DataHub action.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

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
        self._root_identity: frozenset[str] = frozenset()
        self._root_fingerprint: str | None = None
        self._pending_root_identity: frozenset[str] | None = None
        self._pending_root_fingerprint: str | None = None
        self._schema_fingerprints: dict[str, str] = {}
        self._lineage_fingerprints: dict[str, str] = {}
        self._pending_schema_fingerprints: dict[str, str] = {}
        self._probe_cursor = 0
        self._detected_change: str | None = None
        self._actions: dict[str, list[CatalogAction]] = {}
        self._task: asyncio.Task[None] | None = None
        self._refresh_event = asyncio.Event()
        self._refresh_reasons: deque[str] = deque(maxlen=16)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Schedule background loading; never delay API readiness."""

        if not self._settings.catalog_autoload:
            return
        await self._start_worker("server_start")

    async def _start_worker(self, reason: str) -> bool:
        """Start or restart the cache worker after a prior unexpected exit."""

        async with self._lock:
            if self._task and not self._task.done():
                return False
            self._status = CatalogCacheStatus(
                state=CatalogCacheState.RUNNING,
                message="Loading the DataHub 3D catalog in the background.",
                refresh_reason=reason,
                refresh_started_at=datetime.now(UTC),
                refresh_in_progress=True,
                generation=self._status.generation,
            )
            self._task = asyncio.create_task(
                self._run(reason), name="lineageguard-catalog-cache"
            )
        return True

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

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

        reason = reason[:160]
        if await self._start_worker(reason):
            return (await self.snapshot()).status
        async with self._lock:
            if reason not in self._refresh_reasons:
                self._refresh_reasons.append(reason)
            if self._status.state is CatalogCacheState.READY:
                self._status = self._status.model_copy(
                    update={
                        "state": CatalogCacheState.STALE,
                        "message": "Catalog refresh requested; the current graph remains available.",
                        "refresh_reason": reason,
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

    async def _run(self, reason: str) -> None:
        while True:
            await self._guarded_refresh(reason)
            # Stay in the inexpensive polling loop until there is an explicit
            # request, a failed refresh to retry, or an observed change. A
            # ``continue`` on the outer loop would accidentally launch a full
            # traversal after every unchanged poll.
            while True:
                try:
                    await asyncio.wait_for(
                        self._refresh_event.wait(),
                        timeout=self._settings.catalog_refresh_seconds,
                    )
                    self._refresh_event.clear()
                    async with self._lock:
                        reasons = list(self._refresh_reasons)
                        self._refresh_reasons.clear()
                        reason = (
                            "requested:" + ",".join(reasons)
                            if reasons
                            else "requested_refresh"
                        )[:160]
                    break
                except TimeoutError:
                    status = (await self.snapshot()).status
                    if (
                        status.state
                        in {CatalogCacheState.FAILED, CatalogCacheState.STALE}
                        and status.consecutive_failures > 0
                    ):
                        reason = "retry_after_datahub_unavailable"
                        break
                    if await self._guarded_change_check():
                        reason = (
                            f"detected_change:{self._detected_change or 'catalog'}"
                        )[:160]
                        break

    async def _guarded_refresh(self, reason: str) -> None:
        """Cancel stuck work and keep the worker alive after any refresh failure."""

        try:
            await asyncio.wait_for(
                self._refresh(reason),
                timeout=self._settings.catalog_refresh_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._mark_refresh_failure(
                reason,
                f"Catalog refresh exceeded the {self._settings.catalog_refresh_timeout_seconds}s watchdog.",
            )
        except Exception as error:  # noqa: BLE001 - worker must survive parser/provider defects
            await self._mark_refresh_failure(
                reason, f"{type(error).__name__}: {error}"
            )

    async def _guarded_change_check(self) -> bool:
        try:
            changed = await self._catalog_identity_changed()
            async with self._lock:
                self._status = self._status.model_copy(
                    update={"last_checked_at": datetime.now(UTC)}
                )
            return changed
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a poll failure must not kill the worker
            async with self._lock:
                self._status = self._status.model_copy(
                    update={
                        "last_checked_at": datetime.now(UTC),
                        "last_error": f"Change check failed: {type(error).__name__}",
                    }
                )
            return False

    async def _mark_refresh_failure(self, reason: str, detail: str) -> None:
        async with self._lock:
            has_graph = bool(self._graph.nodes)
            failures = self._status.consecutive_failures + 1
            self._status = CatalogCacheStatus(
                state=CatalogCacheState.STALE if has_graph else CatalogCacheState.FAILED,
                loaded_assets=len(self._graph.nodes),
                loaded_edges=len(self._graph.edges),
                message=(
                    "Catalog refresh failed; the previous graph remains available."
                    if has_graph
                    else "Catalog refresh failed; the worker will retry automatically."
                ),
                last_updated_at=self._status.last_updated_at,
                refresh_reason=reason,
                refresh_started_at=self._status.refresh_started_at,
                last_checked_at=datetime.now(UTC),
                refresh_in_progress=False,
                consecutive_failures=failures,
                last_error=detail[:500],
                detected_change=self._detected_change,
                generation=self._status.generation,
            )

    async def _catalog_identity_changed(self) -> bool:
        """Detect root, schema, and direct-lineage changes with bounded reads."""

        try:
            fresh = await self._load_catalog_nodes()
        except (DataHubConfigurationError, OSError, TimeoutError):
            return False
        identity = _root_identity(fresh)
        fingerprint = _root_fingerprint(fresh)
        if identity == self._root_identity and fingerprint == self._root_fingerprint:
            self._pending_root_identity = None
            self._pending_root_fingerprint = None
            return await self._asset_metadata_changed(fresh)

        # A second, identical observation prevents a transient DataHub search
        # ordering/indexing fluctuation from triggering a 1k+ lineage scan.
        if (
            identity != self._pending_root_identity
            or fingerprint != self._pending_root_fingerprint
        ):
            self._pending_root_identity = identity
            self._pending_root_fingerprint = fingerprint
            return False
        self._pending_root_identity = None
        self._pending_root_fingerprint = None
        self._detected_change = "root catalog membership or metadata"
        return True

    async def _asset_metadata_changed(self, roots: list[CatalogNode]) -> bool:
        """Probe a rotating bounded slice for schema or lineage changes."""

        ordered = sorted(roots, key=lambda node: node.urn)
        if not ordered:
            return False
        size = min(self._settings.catalog_change_probe_assets, len(ordered))
        start = self._probe_cursor % len(ordered)
        selected = [ordered[(start + index) % len(ordered)] for index in range(size)]
        self._probe_cursor = (start + size) % len(ordered)
        client = self._client_factory()
        inspect_many = getattr(client, "inspect_catalog_assets", None)
        if callable(inspect_many):
            results = await inspect_many([node.urn for node in selected])
        else:
            semaphore = asyncio.Semaphore(self._settings.catalog_lineage_concurrency)

            async def inspect(node: CatalogNode) -> tuple[dict[str, Any], dict[str, Any]]:
                async with semaphore:
                    schema = await client.list_schema_fields(node.urn)
                    lineage = await client.get_lineage(
                        node.urn, "DOWNSTREAM", 1, max_results=100
                    )
                    return schema, lineage

            results = await asyncio.gather(*(inspect(node) for node in selected))

        if len(results) != len(selected):
            raise DataHubConfigurationError("DataHub returned an incomplete change probe")

        changed: list[str] = []
        for node, (schema_result, lineage_result) in zip(selected, results, strict=True):
            schema_signature = _schema_fingerprint(schema_result)
            lineage_graph = catalog_from_lineage(
                lineage_result, node.urn, "DOWNSTREAM", 1
            )
            lineage_signature = _lineage_fingerprint(lineage_graph, node.urn)
            previous_schema = self._schema_fingerprints.get(node.urn)
            previous_lineage = self._lineage_fingerprints.get(node.urn)
            if previous_schema is None:
                self._schema_fingerprints[node.urn] = schema_signature
            elif previous_schema != schema_signature:
                self._pending_schema_fingerprints[node.urn] = schema_signature
                changed.append(f"schema:{node.urn}")
            if previous_lineage is None:
                self._lineage_fingerprints[node.urn] = lineage_signature
            elif previous_lineage != lineage_signature:
                changed.append(f"lineage:{node.urn}")

        if changed:
            self._detected_change = "; ".join(changed[:3])
            return True
        self._detected_change = None
        return False

    async def _refresh(self, reason: str) -> None:
        async with self._lock:
            had_graph = bool(self._graph.nodes)
            started_at = datetime.now(UTC)
            self._status = CatalogCacheStatus(
                state=CatalogCacheState.RUNNING,
                loaded_assets=len(self._graph.nodes),
                loaded_edges=len(self._graph.edges),
                message=(
                    "Refreshing the DataHub 3D catalog in the background; the existing graph is preserved."
                    if had_graph
                    else "Refreshing the bounded DataHub 3D catalog in the background."
                ),
                last_updated_at=self._status.last_updated_at,
                refresh_reason=reason,
                refresh_started_at=started_at,
                last_checked_at=self._status.last_checked_at,
                refresh_in_progress=True,
                consecutive_failures=self._status.consecutive_failures,
                detected_change=self._detected_change,
                generation=self._status.generation,
            )
        roots = await self._load_catalog_nodes()
        if not roots:
            raise DataHubConfigurationError(
                "DataHub returned an empty catalog; refusing to replace the cached graph"
            )
        if not had_graph:
            async with self._lock:
                # Initial startup has no graph to preserve, so publish roots
                # promptly while lineage batches are discovered.
                self._graph = CatalogGraph(nodes=roots, edges=[], query="*", max_hops=1)
                self._status = self._status.model_copy(
                    update={
                        "state": CatalogCacheState.READY,
                        "loaded_assets": len(roots),
                        "message": "Catalog assets are ready; enriching observed lineage relationships in the background.",
                    }
                )
        graph, lineage_fingerprints = await self._load_lineage_graph(
            roots, publish_progress=not had_graph
        )
        now = datetime.now(UTC)
        async with self._lock:
            self._graph = graph
            self._root_identity = _root_identity(roots)
            self._root_fingerprint = _root_fingerprint(roots)
            self._lineage_fingerprints = lineage_fingerprints
            self._schema_fingerprints.update(self._pending_schema_fingerprints)
            root_urns = {node.urn for node in roots}
            self._schema_fingerprints = {
                urn: signature
                for urn, signature in self._schema_fingerprints.items()
                if urn in root_urns
            }
            self._pending_schema_fingerprints.clear()
            visible_urns = {node.urn for node in graph.nodes}
            self._actions = {
                urn: actions
                for urn, actions in self._actions.items()
                if urn in visible_urns
            }
            self._pending_root_identity = None
            self._pending_root_fingerprint = None
            self._detected_change = None
            self._status = CatalogCacheStatus(
                state=CatalogCacheState.READY,
                loaded_assets=len(graph.nodes),
                loaded_edges=len(graph.edges),
                message="Server-side 3D catalog cache is ready and stays available to every browser.",
                last_updated_at=now,
                refresh_reason=reason,
                refresh_started_at=started_at,
                last_checked_at=now,
                refresh_in_progress=False,
                consecutive_failures=0,
                generation=self._status.generation + 1,
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
        # Querying every schema field before datasets can make the first visible
        # snapshot look disconnected for a long time. DataHub lineage is most
        # useful on datasets and BI/pipeline entities, so traverse those first.
        # This changes only refresh order, never the catalogue contents.
        lineage_priority = {
            "DATASET": 0,
            "DATAFLOW": 1,
            "DATAJOB": 2,
            "DASHBOARD": 3,
            "CHART": 4,
            "CONTAINER": 5,
            "SCHEMAFIELD": 9,
        }
        return sorted(
            nodes.values(),
            key=lambda node: (
                lineage_priority.get(node.entity_type.upper(), 6),
                node.label.casefold(),
                node.urn,
            ),
        )

    async def _load_lineage_graph(
        self, roots: list[CatalogNode], *, publish_progress: bool
    ) -> tuple[CatalogGraph, dict[str, str]]:
        client = self._client_factory()
        async def fetch(root: CatalogNode) -> CatalogGraph | None:
            try:
                result = await client.get_lineage(root.urn, "DOWNSTREAM", 1, max_results=100)
                return catalog_from_lineage(result, root.urn, "DOWNSTREAM", 1)
            except (DataHubConfigurationError, OSError, TimeoutError):
                return None

        nodes: dict[str, CatalogNode] = {node.urn: node for node in roots}
        edges: dict[tuple[str, str, str], CatalogEdge] = {}
        lineage_fingerprints: dict[str, str] = {}
        for start in range(0, len(roots), 50):
            batch = roots[start : start + 50]

            async def fetch_individually() -> list[CatalogGraph | None]:
                """Recover a partial MCP batch without discarding good lineage."""

                semaphore = asyncio.Semaphore(self._settings.catalog_lineage_concurrency)

                async def limited_fetch(root: CatalogNode) -> CatalogGraph | None:
                    async with semaphore:
                        return await fetch(root)

                return await asyncio.gather(*(limited_fetch(root) for root in batch))

            lineage_many = getattr(client, "get_lineage_many", None)
            if callable(lineage_many):
                try:
                    results = await lineage_many(
                        [(root.urn, "DOWNSTREAM", 1, 100) for root in batch]
                    )
                    if len(results) != len(batch):
                        raise DataHubConfigurationError(
                            "DataHub returned fewer lineage responses than requested"
                        )
                    projections = [
                        catalog_from_lineage(result, root.urn, "DOWNSTREAM", 1)
                        for root, result in zip(batch, results, strict=True)
                    ]
                except (DataHubConfigurationError, OSError, TimeoutError):
                    # Some DataHub entities have no valid batch lineage response.
                    # Retry only this batch one asset at a time: successful roots
                    # still contribute their real relationships to the 3D cache.
                    projections = await fetch_individually()
            else:
                projections = await fetch_individually()
            if any(projection is None for projection in projections):
                raise DataHubConfigurationError(
                    f"Lineage refresh returned an incomplete batch at offset {start}"
                )
            for root, projection in zip(batch, projections, strict=True):
                if projection is None:
                    continue
                lineage_fingerprints[root.urn] = _lineage_fingerprint(
                    projection, root.urn
                )
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
        return (
            CatalogGraph(
                nodes=list(nodes.values())[: self._settings.catalog_max_assets],
                edges=list(edges.values())[: self._settings.catalog_max_edges],
                query="*",
                max_hops=1,
                truncated=len(nodes) > self._settings.catalog_max_assets
                or len(edges) > self._settings.catalog_max_edges,
            ),
            lineage_fingerprints,
        )


catalog_cache = CatalogCache()


def _root_identity(nodes: list[CatalogNode]) -> frozenset[str]:
    """Fingerprint root membership only; display metadata is not freshness."""

    return frozenset(node.urn for node in nodes)


def _root_fingerprint(nodes: list[CatalogNode]) -> str:
    """Detect stable catalog metadata changes without depending on result order."""

    projection = [
        {
            "urn": node.urn,
            "label": node.label,
            "entity_type": node.entity_type,
            "platform_urn": node.platform_urn,
            "owner_urns": sorted(node.owner_urns),
        }
        for node in sorted(nodes, key=lambda item: item.urn)
    ]
    return _stable_hash(projection)


def _schema_fingerprint(result: dict[str, Any]) -> str:
    """Hash only the structured schema projection, independent of field order."""

    content = result.get("structuredContent", {})
    if not isinstance(content, dict):
        content = {}
    fields = content.get("fields", [])
    if not isinstance(fields, list):
        fields = []
    normalized = sorted(
        (field for field in fields if isinstance(field, dict)),
        key=lambda field: str(
            field.get("fieldPath") or field.get("name") or _stable_hash(field)
        ),
    )
    return _stable_hash(normalized)


def _lineage_fingerprint(graph: CatalogGraph, root_urn: str) -> str:
    """Hash direct topology for one root, excluding volatile display metadata."""

    edges = sorted(
        (
            edge.source_urn,
            edge.target_urn,
            edge.direction,
            edge.hops,
        )
        for edge in graph.edges
        if edge.source_urn == root_urn or edge.target_urn == root_urn
    )
    return _stable_hash(edges)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
