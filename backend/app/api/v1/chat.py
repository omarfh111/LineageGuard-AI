"""Safe Agentic RAG endpoints: retrieve, verify, then propose actions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient, get_datahub_client
from app.domain.contracts import (
    ChatAnalysisRequest,
    ChatMemoryStatus,
    ChatRequest,
    ChatResponse,
    RagIndexStatus,
    WorkflowAnalysisExecution,
)
from app.services.chat_agent import ChatConfigurationError, HybridChatAgent
from app.services.chat_handoff import (
    ChatHandoffError,
    chat_handoff_store,
)
from app.services.chat_memory import chat_memory_store
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
        settings = get_settings()
        persisted = await persisted_index_status(settings)
        return rag_index_coordinator.start(
            QdrantMetadataIndex(client, settings),
            query_available=persisted.query_available,
        )
    except (RagConfigurationError, DataHubConfigurationError) as error:
        raise HTTPException(503, str(error)) from error


@router.post("/query", response_model=ChatResponse)
async def query(request: ChatRequest, client: DataHubClientDependency) -> ChatResponse:
    try:
        agent = HybridChatAgent(
            client, QdrantMetadataIndex(client, get_settings()), get_settings()
        )
        agent.set_memory_context(
            chat_memory_store.context_for(request.session_id, request.memory_enabled),
            chat_memory_store.active_asset_for(request.session_id, request.memory_enabled),
        )
        response = await agent.respond(request)
        handoff = None
        resolution = response.target_resolution
        if (
            response.action_proposal.action == "ANALYZE_IMPACT"
            and resolution is not None
            and resolution.status == "RESOLVED"
            and len(resolution.targets) == 1
        ):
            handoff = chat_handoff_store.issue(
                request.session_id, resolution.targets[0]
            )
        elif request.session_id:
            chat_handoff_store.clear_session(request.session_id)
        memory = chat_memory_store.record_turn(
            request.session_id, request.memory_enabled, request.message, response.answer,
            response.active_verified_asset,
        )
        return response.model_copy(
            update={
                "memory": memory,
                "analysis_handoff_id": (
                    handoff.handoff_id if handoff is not None else None
                ),
                "analysis_handoff_expires_at": (
                    handoff.expires_at if handoff is not None else None
                ),
            }
        )
    except (RagConfigurationError, ChatConfigurationError, DataHubConfigurationError) as error:
        raise HTTPException(503, str(error)) from error


@router.get("/memory/{session_id}", response_model=ChatMemoryStatus)
async def memory_status(session_id: str) -> ChatMemoryStatus:
    """Return memory metadata only; turn content is never exposed by this endpoint."""

    return chat_memory_store.status(session_id)


@router.delete("/memory/{session_id}", response_model=ChatMemoryStatus)
async def clear_memory(session_id: str) -> ChatMemoryStatus:
    """Explicitly erase the current browser session's stored conversation context."""

    chat_handoff_store.clear_session(session_id)
    return chat_memory_store.clear(session_id)


@router.post("/execute-analysis", response_model=WorkflowAnalysisExecution)
async def execute_analysis(
    request: ChatAnalysisRequest, client: DataHubClientDependency
) -> WorkflowAnalysisExecution:
    """Run only the read-only workflow after explicit user confirmation."""

    if not request.confirmed:
        raise HTTPException(422, "Set confirmed=true before the chat can run an impact analysis")
    try:
        chat_handoff_store.authorize(
            request.handoff_id,
            request.session_id,
            request.change_request.asset_urn,
        )
        return await LineageGuardWorkflow(client=client).analyze(request.change_request)
    except ChatHandoffError as error:
        raise HTTPException(409, str(error)) from error
    except DataHubConfigurationError as error:
        raise HTTPException(503, str(error)) from error
