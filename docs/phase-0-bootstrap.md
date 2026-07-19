# Phase 0 — Bootstrap and compliance

This phase establishes a public-source-ready Apache-2.0 codebase without external product integrations.

## Included

- FastAPI health endpoint: `GET /api/v1/health`
- React/Vite page that presents the API health state
- Environment-variable template with empty secret fields
- Docker Compose service health checks
- GitHub Actions checks for the backend tests and frontend build

## Explicitly deferred

- DataHub Core, DataHub MCP, and all metadata reads/writes
- Agents, workflow state machine, persistence, and contracts
- OpenAI and Groq adapters or any LLM calls
- Authentication, approval flows, and rollback operations

The endpoint reports `not_configured` for deferred dependencies rather than pretending they are available.
