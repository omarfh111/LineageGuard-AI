# LineageGuard AI

> A safety-first impact-analysis application for proposed data-schema changes, built for the **Build with DataHub: The Agent Hackathon** — *Agents That Do Real Work* track.

LineageGuard AI will use the DataHub metadata graph to identify the downstream impact of a schema change, produce an evidence-backed migration and rollback plan, and require human approval before any authorized write-back.

## Current status

The read-only DataHub vertical slice is now available: local DataHub Core, `showcase-ecommerce` sample metadata, and MCP-backed search, schema, and lineage endpoints.

**Phase 0 — Bootstrap and compliance** is complete in this repository. The starter includes a runnable FastAPI service, a React/Vite health page, configuration templates, container definitions, and minimal CI.

The following are intentionally **not** implemented yet:

- autonomous agents, orchestration, or workflow persistence;
- OpenAI, Groq, or any other LLM integration;
- metadata mutations or write-back.

## Architecture direction

```text
React health UI  →  FastAPI API  →  future deterministic workflow
```

The DataHub vertical slice is read-only and invokes the official self-hosted MCP server for search, schema inspection, and lineage traversal. See [the local DataHub guide](docs/datahub-local.md) for setup. Later work will add validated contracts, deterministic risk analysis, planning, independent judges, human approval, and only then controlled write-back.

## Repository layout

```text
backend/        FastAPI service and API tests
frontend/       React/Vite health page
scripts/        Local DataHub bootstrap helper
docs/           Bootstrap and architecture notes
evals/          Reserved for future evaluation assets
examples/       Reserved for reproducible scenarios
.github/        Continuous-integration workflow
```

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- Docker Compose (optional)

## Run locally

Copy the environment template and populate only the variables needed by future phases. Do not commit the resulting `.env` file.

```bash
cp .env.example .env
```

Start the backend:

```bash
cd backend
python -m venv .venv
# Activate the virtual environment using your shell's normal command.
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Alternatively, from the repository root, install the Phase 0 runtime and test dependencies with:

```bash
python -m pip install -r requirements.txt
```

The API health endpoint is available at `http://localhost:8000/api/v1/health`.

In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`). The page queries the API health endpoint. Set `VITE_API_BASE_URL` only when the API is hosted elsewhere.

## Verify

```bash
cd backend
pytest

cd ../frontend
npm run check
```

Or run the bootstrap containers:

```bash
docker compose up --build
```

The backend health check is served on port `8000`; the frontend health page is served on port `5173`.

For local DataHub setup and end-to-end verification, see [the local DataHub guide](docs/datahub-local.md).

## Safety baseline

- Secrets are read from the environment and must never be committed.
- DataHub metadata will be treated as untrusted data, never as instructions.
- Future analysis components will be read-only by default.
- The DataHub MCP bridge allowlists six read tools and starts with mutation tools disabled.
- Any future metadata mutation will require explicit human approval and a pre-mutation snapshot.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
