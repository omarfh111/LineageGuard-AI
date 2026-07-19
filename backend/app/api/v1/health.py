"""Read-only health endpoint for the bootstrap service."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """A deliberately local-only health report for Phase 0."""

    status: Literal["ok"]
    service: str
    environment: str
    datahub: Literal["not_configured"]
    llm_providers: Literal["not_configured"]


@router.get("/health", response_model=HealthResponse)
def read_health() -> HealthResponse:
    """Report service readiness without probing future external integrations."""

    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="lineageguard-api",
        environment=settings.app_env,
        datahub="not_configured",
        llm_providers="not_configured",
    )
