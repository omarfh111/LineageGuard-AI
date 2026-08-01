"""Read-only health endpoint for the bootstrap service."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["health"])


class ProviderReadiness(BaseModel):
    """Safe configuration readiness for one optional model role."""

    available: bool
    model: str | None
    mode: Literal["external", "local_fallback"]
    reason: str


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
    writeback: Literal["disabled", "reviewer_unconfigured", "ready"]
    demo_mode: bool
    providers: dict[str, ProviderReadiness]


@router.get("/health", response_model=HealthResponse)
def read_health() -> HealthResponse:
    """Report safe runtime configuration without exposing credentials."""

    settings = get_settings()
    providers = {
        "chat": _provider_readiness(
            key_present=bool(settings.openai_api_key),
            model=settings.chat_model,
            fallback=settings.demo_mode,
            role="OpenAI chat",
        ),
        "nvidia_critic": _provider_readiness(
            key_present=bool(settings.nvidia_api_key),
            model=settings.nvidia_critic_model,
            role="NVIDIA critic",
        ),
        "openai_judge": _provider_readiness(
            key_present=bool(settings.openai_api_key),
            model=settings.openai_judge_model,
            role="OpenAI judge",
        ),
        "groq_judge": _provider_readiness(
            key_present=bool(settings.groq_api_key),
            model=settings.groq_judge_model,
            role="Groq judge",
        ),
    }
    configured_providers = sum(
        providers[name].available
        for name in ("nvidia_critic", "openai_judge", "groq_judge")
    )
    llm_state: Literal["configured", "partial", "not_configured"]
    if configured_providers >= 2:
        llm_state = "configured"
    elif configured_providers == 1 or settings.demo_mode:
        llm_state = "partial"
    else:
        llm_state = "not_configured"
    writeback_state: Literal["disabled", "reviewer_unconfigured", "ready"]
    if not settings.datahub_writeback_enabled:
        writeback_state = "disabled"
    elif not settings.local_reviewer_capability or len(settings.local_reviewer_capability) < 24:
        writeback_state = "reviewer_unconfigured"
    else:
        writeback_state = "ready"
    return HealthResponse(
        status="ok",
        service="lineageguard-api",
        environment=settings.app_env,
        datahub="configured" if settings.datahub_gms_url else "not_configured",
        llm_providers=llm_state,
        qdrant="configured" if settings.qdrant_url else "not_configured",
        writeback=writeback_state,
        demo_mode=settings.demo_mode,
        providers=providers,
    )


def _provider_readiness(
    *,
    key_present: bool,
    model: str | None,
    role: str,
    fallback: bool = False,
) -> ProviderReadiness:
    """Describe configured capability without probing or leaking credentials."""

    if key_present and model:
        return ProviderReadiness(
            available=True,
            model=model,
            mode="external",
            reason="Configured; availability is confirmed only when the request succeeds.",
        )
    if fallback:
        return ProviderReadiness(
            available=True,
            model="deterministic-demo-fallback",
            mode="local_fallback",
            reason="Using the deterministic local demonstration fallback.",
        )
    missing = "credentials and model" if not key_present and not model else (
        "credentials" if not key_present else "model"
    )
    return ProviderReadiness(
        available=False,
        model=model,
        mode="external",
        reason=f"{role} {missing} are not configured.",
    )
