"""FastAPI entry point for the LineageGuard AI bootstrap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.analysis import router as analysis_router
from app.api.v1.datahub import router as datahub_router
from app.api.v1.health import router as health_router
from app.api.v1.remediation import router as remediation_router

app = FastAPI(
    title="LineageGuard AI API",
    version="0.1.0",
    description=(
        "Read-only DataHub metadata and deterministic schema-impact analysis. "
        "Agents, LLM integrations, and write-back are not enabled."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=[],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(datahub_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(remediation_router, prefix="/api/v1")
