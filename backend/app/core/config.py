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


def get_settings() -> Settings:
    """Return environment-backed bootstrap settings without exposing secrets."""

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./lineageguard.db"),
    )
