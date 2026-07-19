"""Local advisory critique endpoint, deliberately separate from final judges."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.domain.contracts import AdvisoryCritique, CritiqueRequest
from app.services.nvidia_critic import (
    NvidiaConfigurationError,
    NvidiaCritic,
    NvidiaCriticError,
)

router = APIRouter(prefix="/debates", tags=["advisory critique"])


@router.post("/critique", response_model=AdvisoryCritique)
async def critique(request: CritiqueRequest) -> AdvisoryCritique:
    """Run the NVIDIA advisory critique; it neither changes the plan nor calls final judges."""

    try:
        critic = NvidiaCritic(get_settings())
        return await critic.critique(request)
    except NvidiaConfigurationError as error:
        raise HTTPException(503, str(error)) from error
    except NvidiaCriticError as error:
        raise HTTPException(502, str(error)) from error
