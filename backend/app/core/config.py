"""Non-secret application settings used during the bootstrap phase."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime settings with safe local defaults.

    Connections to DataHub and LLM providers are deliberately not initialized
    during Phase 0. Their environment variables remain reserved in `.env.example`.
    """

    app_env: str
    database_url: str
    datahub_gms_url: str
    datahub_gms_token: str | None
    openai_api_key: str | None = None
    openai_judge_model: str | None = None
    groq_api_key: str | None = None
    groq_judge_model: str | None = None
    judge_temperature: float = 0
    judge_timeout_seconds: int = 45
    judge_max_retries: int = 2
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_critic_model: str | None = None
    nvidia_timeout_seconds: int = 90
    datahub_writeback_enabled: bool = False


def get_settings() -> Settings:
    """Return environment-backed bootstrap settings without exposing secrets."""

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./lineageguard.db"),
        datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "").rstrip("/"),
        datahub_gms_token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_judge_model=os.getenv("OPENAI_JUDGE_MODEL") or None,
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_judge_model=os.getenv("GROQ_JUDGE_MODEL") or None,
        judge_temperature=float(os.getenv("JUDGE_TEMPERATURE", "0")),
        judge_timeout_seconds=int(os.getenv("JUDGE_TIMEOUT_SECONDS", "45")),
        judge_max_retries=int(os.getenv("JUDGE_MAX_RETRIES", "2")),
        nvidia_api_key=os.getenv("NVIDIA_API_KEY") or None,
        nvidia_base_url=os.getenv(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ).rstrip("/"),
        nvidia_critic_model=os.getenv("NVIDIA_CRITIC_MODEL") or None,
        nvidia_timeout_seconds=int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "90")),
        datahub_writeback_enabled=os.getenv("DATAHUB_WRITEBACK_ENABLED", "false").lower() == "true",
    )
