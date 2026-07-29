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
    writeback_stale_seconds: int = 300
    langsmith_tracing_enabled: bool = False
    langsmith_project: str | None = None
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "lineageguard_datahub"
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_provider: str = "openai"
    chat_model: str | None = None
    rag_max_assets: int = 1500
    demo_mode: bool = False
    catalog_autoload: bool = True
    catalog_refresh_seconds: int = 60
    catalog_max_assets: int = 1500
    catalog_max_edges: int = 5000
    catalog_lineage_concurrency: int = 8
    chat_memory_enabled: bool = True
    chat_memory_max_turns: int = 6
    chat_memory_context_chars: int = 6000
    chat_memory_ttl_hours: int = 168


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
        writeback_stale_seconds=max(
            30, int(os.getenv("WRITEBACK_STALE_SECONDS", "300"))
        ),
        langsmith_tracing_enabled=(
            _enabled(os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2", "false"))
            and bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
        ),
        langsmith_project=os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or None,
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "lineageguard_datahub"),
        rag_embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small"),
        rag_embedding_provider=os.getenv("RAG_EMBEDDING_PROVIDER", "openai").strip().lower(),
        chat_model=os.getenv("OPENAI_CHAT_MODEL") or os.getenv("OPENAI_JUDGE_MODEL") or None,
        rag_max_assets=int(os.getenv("RAG_MAX_ASSETS", "1500")),
        demo_mode=_enabled(os.getenv("DEMO_MODE", "false")),
        catalog_autoload=_enabled(os.getenv("CATALOG_AUTOLOAD", "true")),
        catalog_refresh_seconds=max(15, int(os.getenv("CATALOG_REFRESH_SECONDS", "60"))),
        catalog_max_assets=max(1, int(os.getenv("CATALOG_MAX_ASSETS", "1500"))),
        catalog_max_edges=max(1, int(os.getenv("CATALOG_MAX_EDGES", "5000"))),
        catalog_lineage_concurrency=max(1, int(os.getenv("CATALOG_LINEAGE_CONCURRENCY", "8"))),
        chat_memory_enabled=_enabled(os.getenv("CHAT_MEMORY_ENABLED", "true")),
        chat_memory_max_turns=max(1, min(20, int(os.getenv("CHAT_MEMORY_MAX_TURNS", "6")))),
        chat_memory_context_chars=max(1000, min(20000, int(os.getenv("CHAT_MEMORY_CONTEXT_CHARS", "6000")))),
        chat_memory_ttl_hours=max(1, min(720, int(os.getenv("CHAT_MEMORY_TTL_HOURS", "168")))),
    )


def configure_langsmith_tracing() -> bool:
    """Normalize legacy LangChain variables for LangGraph/LangSmith tracing.

    Values are read only from the process environment and are never logged or
    returned by the API. Tracing stays disabled unless the user opts in with a
    tracing flag; a missing key simply leaves tracing disabled.
    """

    enabled = _enabled(os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2", "false"))
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not enabled or not api_key:
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    _copy_if_present("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT")
    _copy_if_present("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT")
    return True


def _copy_if_present(target: str, legacy_source: str) -> None:
    if not os.getenv(target) and os.getenv(legacy_source):
        os.environ[target] = os.environ[legacy_source]


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
