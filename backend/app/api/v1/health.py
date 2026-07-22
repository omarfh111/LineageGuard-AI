"""Read-only health endpoint for the bootstrap service."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Configuration health without making external network calls.

    The container probe remains fast and deterministic.  The statuses report
    whether the running API was configured to use a dependency; they never
    claim that a remote provider answered a request.
    """

    status: Literal["ok"]
    service: str
    environment: str
    datahub: Literal["configured", "not_configured"]
    llm_providers: Literal["configured", "partial", "not_configured"]
    qdrant: Literal["configured", "not_configured"]
    demo_mode: bool


@router.get("/health", response_model=HealthResponse)
def read_health() -> HealthResponse:
    """Report safe runtime configuration without exposing credentials."""

    settings = get_settings()
    provider_keys = [
        bool(settings.openai_api_key),
        bool(settings.groq_api_key),
        bool(settings.nvidia_api_key),
    ]
    configured_providers = sum(provider_keys)
    llm_state: Literal["configured", "partial", "not_configured"]
    if configured_providers >= 2:
        llm_state = "configured"
    elif configured_providers == 1 or settings.demo_mode:
        llm_state = "partial"
    else:
        llm_state = "not_configured"
    return HealthResponse(
        status="ok",
        service="lineageguard-api",
        environment=settings.app_env,
        datahub="configured" if settings.datahub_gms_url else "not_configured",
        llm_providers=llm_state,
        qdrant="configured" if settings.qdrant_url else "not_configured",
        demo_mode=settings.demo_mode,
    )
