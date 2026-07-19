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
