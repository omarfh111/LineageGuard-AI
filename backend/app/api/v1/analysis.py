"""Read-only deterministic schema impact analysis endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.datahub.mcp_client import (
    DataHubConfigurationError,
    DataHubMcpClient,
    get_datahub_client,
)
from app.domain.contracts import ChangeRequest, ImpactReport
from app.services.impact_analysis import AnalysisInputError, ImpactAnalysisService

router = APIRouter(prefix="/analyses", tags=["analysis"])
DataHubClientDependency = Annotated[DataHubMcpClient, Depends(get_datahub_client)]


@router.post("/impact", response_model=ImpactReport)
async def analyze_schema_impact(
    request: ChangeRequest,
    client: DataHubClientDependency,
) -> ImpactReport:
    """Analyze a proposed schema change using only read-only DataHub MCP tools."""

    try:
        return await ImpactAnalysisService(client).analyze(request)
    except DataHubConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except AnalysisInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
