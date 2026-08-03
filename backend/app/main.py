"""FastAPI entry point for the LineageGuard AI bootstrap."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.v1.analysis import router as analysis_router
from app.api.v1.chat import router as chat_router
from app.api.v1.datahub import router as datahub_router
from app.api.v1.debate import router as debate_router
from app.api.v1.health import router as health_router
from app.api.v1.judging import router as judging_router
from app.api.v1.remediation import router as remediation_router
from app.api.v1.writeback import router as writeback_router
from app.api.v1.workflow import router as workflow_router
from app.core.config import configure_langsmith_tracing
from app.services.catalog_cache import catalog_cache

configure_langsmith_tracing()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the server-owned catalog loader without delaying API readiness."""

    await catalog_cache.start()
    try:
        yield
    finally:
        await catalog_cache.stop()


app = FastAPI(
    title="LineageGuard AI API",
    version="0.1.0",
    description=(
        "Evidence-backed DataHub impact analysis with independent judges and "
        "human-approved, auditable document write-back."
    ),
    lifespan=lifespan,
)


cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-LineageGuard-Reviewer-Capability"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(datahub_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(remediation_router, prefix="/api/v1")
app.include_router(debate_router, prefix="/api/v1")
app.include_router(judging_router, prefix="/api/v1")
app.include_router(writeback_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
