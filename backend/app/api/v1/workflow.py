"""LangGraph-backed workflow endpoints used by the interactive UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient, get_datahub_client
from app.domain.contracts import (
    ChangeRequest,
    CritiqueRequest,
    JudgingRequest,
    WorkflowAnalysisExecution,
    WorkflowCritiqueExecution,
    WorkflowJudgingExecution,
    WorkflowVisualization,
)
from app.services.judging import JudgeConfigurationError
from app.services.impact_analysis import AnalysisInputError
from app.services.metadata_investigator import MetadataInvestigationError
from app.services.nvidia_critic import NvidiaConfigurationError, NvidiaCriticError
from app.services.workflow_graph import LineageGuardWorkflow

router = APIRouter(prefix="/workflows", tags=["workflow"])
DataHubClientDependency = Annotated[DataHubMcpClient, Depends(get_datahub_client)]


@router.get("/graph", response_model=WorkflowVisualization)
def graph_definition() -> WorkflowVisualization:
    """Return the safe, static topology for the dynamic graph UI."""

    return LineageGuardWorkflow().visualization()


@router.post("/analyze", response_model=WorkflowAnalysisExecution)
async def analyze(request: ChangeRequest, client: DataHubClientDependency) -> WorkflowAnalysisExecution:
    try:
        return await LineageGuardWorkflow(client=client).analyze(request)
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
async def judge(request: JudgingRequest) -> WorkflowJudgingExecution:
    try:
        return await LineageGuardWorkflow().judge(request)
    except JudgeConfigurationError as error:
        raise HTTPException(503, str(error)) from error
