"""Double independent LLM-as-a-Judge endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domain.contracts import (
    JudgingRunSummary,
    StoredAnalysisJudgingRequest,
    StoredJudgingResult,
)
from app.services.run_store import analysis_store, run_store
from app.services.judging import (
    JudgeConfigurationError,
    JudgingService,
    get_judging_service,
)

router = APIRouter(prefix="/judges", tags=["judging"])
JudgingServiceDependency = Annotated[JudgingService, Depends(get_judging_service)]


@router.post("/evaluate", response_model=StoredJudgingResult)
async def evaluate_report(
    request: StoredAnalysisJudgingRequest,
    service: JudgingServiceDependency,
) -> StoredJudgingResult:
    """Judge only a server-owned deterministic analysis snapshot."""

    try:
        judging_request = analysis_store.get(
            request.analysis_run_id, request.repair_cycles
        )
        if judging_request is None:
            raise HTTPException(404, "Unknown server-owned analysis run")
        result = await service.evaluate(judging_request)
        return StoredJudgingResult(
            run_id=run_store.save(judging_request, result), result=result
        )
    except JudgeConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/history", response_model=list[JudgingRunSummary])
def history(limit: int = Query(default=12, ge=1, le=100)) -> list[JudgingRunSummary]:
    """Display recent persisted judging outcomes without returning the source payload."""

    return run_store.list_recent(limit)
