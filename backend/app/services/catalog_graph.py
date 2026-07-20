"""Safe adapters from raw MCP responses to a bounded interactive catalog graph."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import CatalogEdge, CatalogGraph, CatalogNode


def catalog_from_search(result: dict[str, Any], query: str) -> CatalogGraph:
    content = _structured(result)
    rows = content.get("searchResults", [])
    if not isinstance(rows, list):
        rows = []
    nodes = _unique_nodes(_node_from_entity(row.get("entity", {}), row.get("degree")) for row in rows if isinstance(row, dict))
    return CatalogGraph(nodes=nodes[:100], edges=[], query=query, truncated=len(nodes) > 100)


def catalog_from_lineage(
    result: dict[str, Any], root_urn: str, direction: Literal["UPSTREAM", "DOWNSTREAM"], max_hops: int
) -> CatalogGraph:
    content = _structured(result)
    collection_name = "downstreams" if direction == "DOWNSTREAM" else "upstreams"
    collection = content.get(collection_name, {})
    if not isinstance(collection, dict):
        collection = {}
    rows = collection.get("searchResults", [])
    if not isinstance(rows, list):
        rows = []

    root = CatalogNode(urn=root_urn, label=_label_from_urn(root_urn), entity_type="DATASET", degree=0)
    nodes = [root]
    edges: list[CatalogEdge] = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        node = _node_from_entity(row.get("entity", {}), row.get("degree"))
        if node is None or node.urn == root_urn:
            continue
        nodes.append(node)
        hops = node.degree if isinstance(node.degree, int) and node.degree > 0 else 1
        if direction == "DOWNSTREAM":
            edges.append(CatalogEdge(source_urn=root_urn, target_urn=node.urn, direction=direction, hops=hops))
        else:
            edges.append(CatalogEdge(source_urn=node.urn, target_urn=root_urn, direction=direction, hops=hops))

    total = collection.get("total")
    return CatalogGraph(
        nodes=_unique_nodes(nodes), edges=edges, max_hops=max_hops,
        truncated=isinstance(total, int) and total > len(edges),
    )


async def catalog_snapshot(
    client: DataHubMcpClient, max_assets: int = 250, max_edges: int = 1000, offset: int = 0
) -> CatalogGraph:
    """Build one bounded catalog page from search plus observed links.

    This deliberately caps both assets and links. It is a navigable projection
    of the current DataHub catalog, never a hidden bulk export or a fabricated
    relationship graph.
    """

    nodes: list[CatalogNode] = []
    search_offset = offset
    while len(nodes) < max_assets:
        page = catalog_from_search(
            await client.search("*", num_results=min(50, max_assets - len(nodes)), offset=search_offset), "*"
        )
        if not page.nodes:
            break
        before = len(nodes)
        nodes = _unique_nodes([*nodes, *page.nodes])[:max_assets]
        search_offset += 50
        if len(page.nodes) < 50 or len(nodes) == before:
            break

    # MCP calls launch isolated read-only processes. Ten concurrent calls keep
    # a small local showcase responsive while avoiding an unbounded fan-out.
    semaphore = asyncio.Semaphore(10)

    async def fetch_edges(node: CatalogNode) -> CatalogGraph:
        async with semaphore:
            return catalog_from_lineage(
                await client.get_lineage(node.urn, "DOWNSTREAM", 1, max_results=100),
                node.urn,
                "DOWNSTREAM",
                1,
            )

    projections = await asyncio.gather(*(fetch_edges(node) for node in nodes))
    all_nodes = _unique_nodes([*nodes, *(node for projection in projections for node in projection.nodes)])[:max_assets]
    known = {node.urn for node in all_nodes}
    edges: dict[tuple[str, str, str], CatalogEdge] = {}
    for projection in projections:
        for edge in projection.edges:
            if edge.source_urn in known and edge.target_urn in known and len(edges) < max_edges:
                edges.setdefault((edge.source_urn, edge.target_urn, edge.direction), edge)
    return CatalogGraph(
        nodes=all_nodes,
        edges=list(edges.values()),
        query="*",
        max_hops=1,
        truncated=len(nodes) >= max_assets or len(edges) >= max_edges,
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("structuredContent", {})
    return content if isinstance(content, dict) else {}


def _node_from_entity(entity: Any, degree: Any) -> CatalogNode | None:
    if not isinstance(entity, dict):
        return None
    urn = entity.get("urn")
    if not isinstance(urn, str) or not urn.startswith("urn:li:"):
        return None
    properties = entity.get("properties", {})
    name = properties.get("name") if isinstance(properties, dict) else None
    platform = entity.get("platform", {})
    platform_urn = platform.get("urn") if isinstance(platform, dict) and isinstance(platform.get("urn"), str) else _platform_from_urn(urn)
    ownership = entity.get("ownership", {})
    owners = ownership.get("owners", []) if isinstance(ownership, dict) else []
    owner_urns = [
        item["owner"]["urn"] for item in owners
        if isinstance(item, dict) and isinstance(item.get("owner"), dict) and isinstance(item["owner"].get("urn"), str)
    ]
    return CatalogNode(
        urn=urn, label=name if isinstance(name, str) and name else _label_from_urn(urn),
        entity_type=str(entity.get("type") or _entity_type_from_urn(urn)), platform_urn=platform_urn,
        owner_urns=owner_urns, degree=degree if isinstance(degree, int) else None,
    )


def _unique_nodes(nodes: list[CatalogNode | None] | Any) -> list[CatalogNode]:
    unique: dict[str, CatalogNode] = {}
    for node in nodes:
        if node is not None:
            unique.setdefault(node.urn, node)
    return list(unique.values())


def _label_from_urn(urn: str) -> str:
    return urn.rsplit(",", 1)[-1].rstrip(")") if "," in urn else urn.rsplit(":", 1)[-1]


def _entity_type_from_urn(urn: str) -> str:
    """Derive an entity type when lightweight DataHub search omits it."""

    parts = urn.split(":", 3)
    return parts[2].upper() if len(parts) > 2 and parts[2] else "UNKNOWN"


def _platform_from_urn(urn: str) -> str | None:
    """Derive the platform from standard dataset URNs without inventing data."""

    marker = "urn:li:dataPlatform:"
    if marker not in urn:
        return None
    platform = urn.split(marker, 1)[1].split(",", 1)[0].split(")", 1)[0]
    return f"{marker}{platform}" if platform else None
