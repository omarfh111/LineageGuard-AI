"""FastAPI entry point for the LineageGuard AI bootstrap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.datahub import router as datahub_router
from app.api.v1.health import router as health_router

app = FastAPI(
    title="LineageGuard AI API",
    version="0.1.0",
    description="Bootstrap API. DataHub, agents, and LLM integrations are not enabled yet.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(datahub_router, prefix="/api/v1")
