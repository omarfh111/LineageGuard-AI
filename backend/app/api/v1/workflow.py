"""LangGraph-backed workflow endpoints used by the interactive UI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient, get_datahub_client
from app.domain.contracts import (
    ChangeRequest,
    CritiqueRequest,
    StoredAnalysisJudgingRequest,
    WorkflowAnalysisExecution,
    WorkflowCritiqueExecution,
    WorkflowJudgingExecution,
    WorkflowVisualization,
)
from app.services.judging import (
    JudgeConfigurationError,
    JudgingService,
    get_judging_service,
)
from app.services.impact_analysis import AnalysisInputError
from app.services.metadata_investigator import MetadataInvestigationError
from app.services.nvidia_critic import NvidiaConfigurationError, NvidiaCriticError
from app.services.run_store import analysis_store
from app.services.workflow_graph import LineageGuardWorkflow
from app.services.catalog_cache import catalog_cache

router = APIRouter(prefix="/workflows", tags=["workflow"])
DataHubClientDependency = Annotated[DataHubMcpClient, Depends(get_datahub_client)]
JudgingServiceDependency = Annotated[JudgingService, Depends(get_judging_service)]


@router.get("/graph", response_model=WorkflowVisualization)
def graph_definition() -> WorkflowVisualization:
    """Return the safe, static topology for the dynamic graph UI."""

    return LineageGuardWorkflow().visualization()


@router.get("/analysis/{analysis_run_id}", response_model=WorkflowAnalysisExecution)
def restore_analysis(analysis_run_id: UUID) -> WorkflowAnalysisExecution:
    """Restore a server-owned read-only analysis after a browser reload.

    The endpoint never restores judge results, reviewer capabilities, approval
    state, or idempotency keys.  Those authorities must be earned again.
    """

    execution = LineageGuardWorkflow().restore_analysis(str(analysis_run_id))
    if execution is None:
        raise HTTPException(404, "Unknown server-owned analysis run")
    return execution


@router.post("/analyze", response_model=WorkflowAnalysisExecution)
async def analyze(request: ChangeRequest, client: DataHubClientDependency) -> WorkflowAnalysisExecution:
    try:
        execution = await LineageGuardWorkflow(client=client).analyze(request)
        await catalog_cache.record_action(
            request.asset_urn,
            "IMPACT_ANALYSIS_COMPLETED",
            f"Read-only {request.change_type.value} impact analysis completed for column {request.column_name or 'not specified'}.",
        )
        return execution
    except DataHubConfigurationError as error:
        raise HTTPException(503, str(error)) from error
    except (AnalysisInputError, MetadataInvestigationError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/critique", response_model=WorkflowCritiqueExecution)
async def critique(request: CritiqueRequest) -> WorkflowCritiqueExecution:
    try:
        return await LineageGuardWorkflow().critique(request)
    except NvidiaConfigurationError as error:
        raise HTTPException(503, str(error)) from error
    except NvidiaCriticError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/judge", response_model=WorkflowJudgingExecution)
async def judge(
    request: StoredAnalysisJudgingRequest,
    service: JudgingServiceDependency,
) -> WorkflowJudgingExecution:
    try:
        judging_request = analysis_store.get(
            request.analysis_run_id, request.repair_cycles
        )
        if judging_request is None:
            raise HTTPException(404, "Unknown server-owned analysis run")
        return await LineageGuardWorkflow(judges=service).judge(judging_request)
    except JudgeConfigurationError as error:
        raise HTTPException(503, str(error)) from error
