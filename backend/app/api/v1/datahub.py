"""Read-only DataHub vertical-slice endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.datahub.mcp_client import (
    DataHubConfigurationError,
    DataHubMcpClient,
    get_datahub_client,
)
from app.domain.contracts import CatalogGraph
from app.services.catalog_graph import catalog_from_lineage, catalog_from_search, catalog_snapshot

router = APIRouter(prefix="/datahub", tags=["datahub"])
DataHubClientDependency = Annotated[DataHubMcpClient, Depends(get_datahub_client)]


class McpToolResponse(BaseModel):
    """Unmodified protocol data returned by an allowlisted MCP read tool."""

    tool: str
    result: dict[str, Any]


def _service_unavailable(error: DataHubConfigurationError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


@router.get("/search", response_model=McpToolResponse)
async def search_assets(
    client: DataHubClientDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
) -> McpToolResponse:
    """Search real DataHub metadata through the official MCP server."""

    try:
        result = await client.search(query)
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error
    return McpToolResponse(tool="search", result=result)


@router.get("/schema", response_model=McpToolResponse)
async def list_schema_fields(
    client: DataHubClientDependency,
    asset_urn: Annotated[str, Query(min_length=1)],
) -> McpToolResponse:
    """Retrieve schema fields for an existing DataHub dataset URN."""

    try:
        result = await client.list_schema_fields(asset_urn)
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error
    return McpToolResponse(tool="list_schema_fields", result=result)


@router.get("/lineage", response_model=McpToolResponse)
async def get_lineage(
    client: DataHubClientDependency,
    asset_urn: Annotated[str, Query(min_length=1)],
    direction: Literal["UPSTREAM", "DOWNSTREAM"] = "DOWNSTREAM",
    max_hops: Annotated[int, Query(ge=1, le=5)] = 3,
) -> McpToolResponse:
    """Retrieve bounded upstream or downstream lineage for an existing asset."""

    try:
        result = await client.get_lineage(asset_urn, direction, max_hops)
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error
    return McpToolResponse(tool="get_lineage", result=result)


@router.get("/catalog/search", response_model=CatalogGraph)
async def search_catalog(
    client: DataHubClientDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
) -> CatalogGraph:
    """Return a safe, bounded asset projection for the catalog graph UI."""

    try:
        return catalog_from_search(await client.search(query), query)
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error


@router.get("/catalog/expand", response_model=CatalogGraph)
async def expand_catalog(
    client: DataHubClientDependency,
    asset_urn: Annotated[str, Query(min_length=1)],
    direction: Literal["UPSTREAM", "DOWNSTREAM"] = "DOWNSTREAM",
    max_hops: Annotated[int, Query(ge=1, le=5)] = 2,
) -> CatalogGraph:
    """Expand a selected asset on demand; never exports the entire catalog."""

    try:
        result = await client.get_lineage(asset_urn, direction, max_hops, max_results=100)
        return catalog_from_lineage(result, asset_urn, direction, max_hops)
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error


@router.get("/catalog/snapshot", response_model=CatalogGraph)
async def full_catalog_snapshot(
    client: DataHubClientDependency,
    max_assets: Annotated[int, Query(ge=1, le=250)] = 250,
    max_edges: Annotated[int, Query(ge=1, le=1000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogGraph:
    """Return one relation-aware page for the progressive 3D catalog graph."""

    try:
        return await catalog_snapshot(
            client, max_assets=max_assets, max_edges=max_edges, offset=offset
        )
    except DataHubConfigurationError as error:
        raise _service_unavailable(error) from error
