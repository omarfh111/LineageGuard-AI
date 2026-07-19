"""HITL-controlled report write-back endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubMcpClient, get_datahub_client
from app.domain.contracts import ApprovalRequest, AuditEvent, WritebackPreparationRequest, WritebackProposal
from app.services.run_store import run_store
from app.services.writeback import (
    McpDocumentWriter,
    WritebackError,
    WritebackRepository,
    WritebackService,
)

router = APIRouter(prefix="/writebacks", tags=["writeback"])
_service: WritebackService | None = None


class PrepareRequest(BaseModel):
    run_id: str
    idempotency_key: str = Field(min_length=8, max_length=200)


def get_writeback_service(
    client: Annotated[DataHubMcpClient, Depends(get_datahub_client)],
) -> WritebackService:
    global _service
    if _service is None:
        _service = WritebackService(
            McpDocumentWriter(client),
            WritebackRepository(get_settings().database_url),
        )
    return _service


@router.post("/prepare", response_model=WritebackProposal)
def prepare(
    request: PrepareRequest,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposal:
    stored = run_store.get(request.run_id)
    if not stored:
        raise HTTPException(404, "Unknown server-owned judging run")
    try:
        return service.prepare(
            WritebackPreparationRequest(
                judging_request=stored[0],
                judging_result=stored[1],
                idempotency_key=request.idempotency_key,
            )
        )
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/{run_id}", response_model=WritebackProposal)
def get_proposal(
    run_id: str,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposal:
    proposal = service.get(run_id)
    if not proposal:
        raise HTTPException(404, "Unknown write-back proposal")
    return proposal


@router.get("/{run_id}/audit", response_model=list[AuditEvent])
def get_audit(
    run_id: str,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> list[AuditEvent]:
    if not service.get(run_id):
        raise HTTPException(404, "Unknown write-back proposal")
    return service.audit_events(run_id)


@router.post("/{run_id}/approve", response_model=WritebackProposal)
async def approve(
    run_id: str,
    request: ApprovalRequest,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposal:
    try:
        return await service.decide(run_id, request)
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/{run_id}/rollback", response_model=WritebackProposal)
async def rollback(
    run_id: str,
    request: ApprovalRequest,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposal:
    try:
        return await service.rollback(run_id, request)
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error
