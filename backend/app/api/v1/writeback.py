"""HITL-controlled report write-back endpoints."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.datahub.mcp_client import DataHubMcpClient, get_datahub_client
from app.domain.contracts import (
    ApprovalRequest,
    AuditEvent,
    WritebackPreparationRequest,
    WritebackProposalView,
    WritebackReconciliationRequest,
)
from app.services.run_store import run_store
from app.services.writeback import (
    McpDocumentWriter,
    WritebackConflict,
    WritebackError,
    WritebackOutcomeUnknown,
    WritebackRepository,
    WritebackService,
)
from app.services.catalog_cache import catalog_cache

router = APIRouter(prefix="/writebacks", tags=["writeback"])
_service: WritebackService | None = None


class PrepareRequest(BaseModel):
    run_id: str
    idempotency_key: str = Field(min_length=8, max_length=200)


def require_local_reviewer_capability(
    provided: Annotated[
        str | None,
        Header(alias="X-LineageGuard-Reviewer-Capability"),
    ] = None,
) -> None:
    """Fail closed before any local workflow state or DataHub write can change."""

    settings = get_settings()
    if not settings.datahub_writeback_enabled:
        raise HTTPException(
            503,
            "Write-back is disabled. Set DATAHUB_WRITEBACK_ENABLED=true only for an explicitly approved disposable workflow.",
        )
    expected = settings.local_reviewer_capability
    if not expected or len(expected) < 24:
        raise HTTPException(
            503,
            "Local reviewer capability is not configured with at least 24 characters.",
        )
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "A valid local reviewer capability is required.")


def get_writeback_service(
    client: Annotated[DataHubMcpClient, Depends(get_datahub_client)],
) -> WritebackService:
    global _service
    if _service is None:
        _service = WritebackService(
            McpDocumentWriter(client),
            WritebackRepository(get_settings().database_url),
            stale_after_seconds=get_settings().writeback_stale_seconds,
        )
    return _service


@router.post("/prepare", response_model=WritebackProposalView)
def prepare(
    request: PrepareRequest,
    _: Annotated[None, Depends(require_local_reviewer_capability)],
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposalView:
    stored = run_store.get(request.run_id)
    if not stored:
        raise HTTPException(404, "Unknown server-owned judging run")
    try:
        proposal = service.prepare(
            WritebackPreparationRequest(
                judging_request=stored[0],
                judging_result=stored[1],
                idempotency_key=request.idempotency_key,
            )
        )
        return WritebackProposalView.from_proposal(proposal)
    except WritebackConflict as error:
        raise HTTPException(409, str(error)) from error
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/{run_id}", response_model=WritebackProposalView)
def get_proposal(
    run_id: str,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposalView:
    proposal = service.get(run_id)
    if not proposal:
        raise HTTPException(404, "Unknown write-back proposal")
    return WritebackProposalView.from_proposal(proposal)


@router.get("/{run_id}/audit", response_model=list[AuditEvent])
def get_audit(
    run_id: str,
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> list[AuditEvent]:
    if not service.get(run_id):
        raise HTTPException(404, "Unknown write-back proposal")
    return service.audit_events(run_id)


@router.post("/{run_id}/approve", response_model=WritebackProposalView)
async def approve(
    run_id: str,
    request: ApprovalRequest,
    _: Annotated[None, Depends(require_local_reviewer_capability)],
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposalView:
    try:
        outcome = await service.decide_with_outcome(run_id, request)
        proposal = outcome.proposal
        if outcome.performed and proposal.status == "COMPLETED":
            await catalog_cache.record_action(
                proposal.target_asset_urn,
                "ANALYSIS_DOCUMENT_WRITTEN",
                f"Human-approved DataHub Analysis document created: {proposal.snapshot.get('document_urn', 'unknown URN')}.",
            )
            await catalog_cache.request_refresh("approved_analysis_document_writeback")
        return WritebackProposalView.from_proposal(proposal)
    except (WritebackConflict, WritebackOutcomeUnknown) as error:
        raise HTTPException(409, str(error)) from error
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/{run_id}/rollback", response_model=WritebackProposalView)
async def rollback(
    run_id: str,
    request: ApprovalRequest,
    _: Annotated[None, Depends(require_local_reviewer_capability)],
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposalView:
    try:
        outcome = await service.rollback_with_outcome(run_id, request)
        proposal = outcome.proposal
        if outcome.performed and proposal.status == "ROLLED_BACK":
            await catalog_cache.record_action(
                proposal.target_asset_urn,
                "ANALYSIS_DOCUMENT_SUPERSEDED",
                f"Human-approved compensation completed for {proposal.snapshot.get('document_urn', 'unknown URN')}.",
            )
            await catalog_cache.request_refresh("analysis_document_compensation")
        return WritebackProposalView.from_proposal(proposal)
    except (WritebackConflict, WritebackOutcomeUnknown) as error:
        raise HTTPException(409, str(error)) from error
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/{run_id}/reconcile", response_model=WritebackProposalView)
async def reconcile(
    run_id: str,
    request: WritebackReconciliationRequest,
    _: Annotated[None, Depends(require_local_reviewer_capability)],
    service: Annotated[WritebackService, Depends(get_writeback_service)],
) -> WritebackProposalView:
    """Resolve an uncertain create only after explicit human verification."""

    try:
        return WritebackProposalView.from_proposal(
            await service.reconcile(run_id, request)
        )
    except (WritebackConflict, WritebackOutcomeUnknown) as error:
        raise HTTPException(409, str(error)) from error
    except WritebackError as error:
        raise HTTPException(422, str(error)) from error
