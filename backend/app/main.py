"""FastAPI entry point for the LineageGuard AI bootstrap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.analysis import router as analysis_router
from app.api.v1.datahub import router as datahub_router
from app.api.v1.debate import router as debate_router
from app.api.v1.health import router as health_router
from app.api.v1.judging import router as judging_router
from app.api.v1.remediation import router as remediation_router
from app.api.v1.writeback import router as writeback_router

app = FastAPI(
    title="LineageGuard AI API",
    version="0.1.0",
    description=(
        "Evidence-backed DataHub impact analysis with independent judges and "
        "human-approved, auditable document write-back."
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
app.include_router(debate_router, prefix="/api/v1")
app.include_router(judging_router, prefix="/api/v1")
app.include_router(writeback_router, prefix="/api/v1")
