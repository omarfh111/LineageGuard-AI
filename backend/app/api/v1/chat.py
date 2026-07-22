"""Safe Agentic RAG endpoints: retrieve, verify, then propose actions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient, get_datahub_client
from app.domain.contracts import ChatAnalysisRequest, ChatRequest, ChatResponse, RagIndexStatus, WorkflowAnalysisExecution
from app.services.chat_agent import ChatConfigurationError, HybridChatAgent
from app.services.rag_index import (
    QdrantMetadataIndex,
    RagConfigurationError,
    persisted_index_status,
    rag_index_coordinator,
)
from app.services.workflow_graph import LineageGuardWorkflow

router = APIRouter(prefix="/chat", tags=["agentic-rag"])
DataHubClientDependency = Annotated[DataHubMcpClient, Depends(get_datahub_client)]


@router.get("/index/status", response_model=RagIndexStatus)
async def index_status() -> RagIndexStatus:
    current = rag_index_coordinator.status()
    return current if current.state != "IDLE" else await persisted_index_status(get_settings())


@router.post("/index/ingest", response_model=RagIndexStatus, status_code=status.HTTP_202_ACCEPTED)
async def ingest_metadata(client: DataHubClientDependency) -> RagIndexStatus:
    """Start one background, metadata-only DataHub ingestion into Qdrant."""

    try:
        return rag_index_coordinator.start(QdrantMetadataIndex(client, get_settings()))
    except (RagConfigurationError, DataHubConfigurationError) as error:
        raise HTTPException(503, str(error)) from error


@router.post("/query", response_model=ChatResponse)
async def query(request: ChatRequest, client: DataHubClientDependency) -> ChatResponse:
    try:
        return await HybridChatAgent(
            client, QdrantMetadataIndex(client, get_settings()), get_settings()
        ).respond(request)
    except (RagConfigurationError, ChatConfigurationError, DataHubConfigurationError) as error:
        raise HTTPException(503, str(error)) from error


@router.post("/execute-analysis", response_model=WorkflowAnalysisExecution)
async def execute_analysis(
    request: ChatAnalysisRequest, client: DataHubClientDependency
) -> WorkflowAnalysisExecution:
    """Run only the read-only workflow after explicit user confirmation."""

    if not request.confirmed:
        raise HTTPException(422, "Set confirmed=true before the chat can run an impact analysis")
    try:
        return await LineageGuardWorkflow(client=client).analyze(request.change_request)
    except DataHubConfigurationError as error:
        raise HTTPException(503, str(error)) from error
