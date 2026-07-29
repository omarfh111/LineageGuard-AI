# Operations runbook

This runbook is for a local Windows and Docker Desktop deployment. It is designed for the hackathon demo, not for production operation.

## 1. Prepare the workstation

From the repository root:

```powershell
Copy-Item .env.example .env
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
Push-Location frontend
npm install
Pop-Location

docker version
docker compose version
```

Docker Desktop must show **Engine running** and use Linux containers. WSL 2 is sufficient; Windows containers are not required.

## 2. Start local DataHub

```powershell
.\scripts\start-datahub.ps1
```

The startup script loads `showcase-ecommerce` unless `-SkipDatapack` was supplied. Open <http://localhost:9002> and confirm that the showcase catalog contains assets. To reload it later, run `./scripts/load-showcase-data.ps1`. Inside LineageGuard containers use `http://host.docker.internal:8080`; for a locally run backend use `http://localhost:8080`.

## 3. Configure only the needed providers

Put secrets only in `.env`. Never print them in PowerShell, terminal history, screenshots, commits, or LangSmith exports.

| Capability | Required variables | Optional? |
|---|---|---|
| DataHub read bridge | `DATAHUB_GMS_URL`; token required for non-local DataHub | No |
| 3D catalog cache | `CATALOG_*` | No, defaults are safe |
| Local metadata index | `QDRANT_*`, `RAG_EMBEDDING_*` | No, local hash demo mode exists |
| RAG planning and answer generation | `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL` | Yes; demo fallback is available |
| NVIDIA advisory critique | `NVIDIA_API_KEY`, `NVIDIA_CRITIC_MODEL` | Yes |
| OpenAI factual judge | `OPENAI_API_KEY`, `OPENAI_JUDGE_MODEL` | Yes |
| Groq technical/safety judge | `GROQ_API_KEY`, `GROQ_JUDGE_MODEL` | Yes |
| LangSmith tracing | `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Yes |

Example non-secret shape:

```env
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_WRITEBACK_ENABLED=false

OPENAI_CHAT_MODEL=gpt-4.1-mini
OPENAI_JUDGE_MODEL=gpt-4.1-mini
GROQ_JUDGE_MODEL=openai/gpt-oss-20b
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_TIMEOUT_SECONDS=90

LANGSMITH_TRACING=true
LANGSMITH_PROJECT=lineageguard-ai
```

`WORKER_LLM_PROVIDER` and `WORKER_LLM_MODEL` are not consumed by the current application. The chat uses `OPENAI_CHAT_MODEL`; NVIDIA is an advisory critic only.

## 4. Start the application

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
```

Expected services are `backend`, `frontend`, and `qdrant`, all healthy. Open <http://localhost:5173> only after the health check returns `status: ok`.

## 5. Startup sequence and catalog cache

1. Starting the backend schedules a server-owned 3D catalog load.
2. The root catalog becomes `READY` after its bounded assets are available. This may occur before all relationships have been enriched.
3. The UI polls the cache every five seconds and remains interactive while edges are being added in the background.
4. The API polls root URNs at the configured interval. A real changed identity must persist for two consecutive polls before a full refresh starts.
5. A manual refresh or a LineageGuard action marks the graph stale, keeps the old graph visible, and performs an atomic graph replacement when finished.

Do not expect the **Load 50 more assets** control when the cache already holds every discovered asset within `CATALOG_MAX_ASSETS`.

## 6. Standard demo procedure

1. Confirm DataHub, Qdrant, and provider configuration through `/api/v1/health`.
2. Open the 3D catalog; wait until its asset count is non-zero and the status says `READY`.
3. Hover and select a node to show its URN, type, platform, owner count, and in-session actions.
4. Index DataHub metadata in the RAG panel. After the first successful index, re-indexing remains non-blocking.
5. Ask one schema or lineage question. Show the target-resolution card, MCP citations, and verification result.
6. Resolve an asset in chat and transfer the verified target to the analysis
   form. Confirm that the URN is locked until explicitly unlocked.
7. Exercise all four change contracts: nullable `ADD_COLUMN`, `RENAME_COLUMN`
   with a distinct new name, `CHANGE_COLUMN_TYPE` with compatibility status,
   and `DROP_COLUMN`. Show evidence, risk score, and `NOT_EXECUTED` plans.
8. Edit one field after a completed analysis and confirm that the old report,
   judges, and HITL proposal are invalidated.
9. On a disposable proposal, enter reviewer feedback and select
   `REQUEST_REVISION`. Confirm that unchanged resubmission is blocked and the
   changed request restarts from analysis.
10. If external keys are intentionally enabled, run NVIDIA then the independent judges. Explain that `NEEDS_REPAIR`, `AWAITING_HUMAN`, and `BLOCKED` are safety outcomes, not application failures.
11. Keep write-back disabled unless running the dedicated disposable write proof.

## 7. Tracing and operational observability

With LangSmith enabled, inspect the `lineageguard-ai` project for these root traces:

- `lineageguard_agentic_rag_request`
- `lineageguard_nvidia_advisory_critic`
- `lineageguard_openai_judge`
- `lineageguard_groq_judge`

Use trace hierarchy and metadata to inspect latency and errors. Do not export raw trace inputs or outputs to a public hackathon artifact without reviewing them for metadata that should remain private. LangGraph tracing is automatic once the environment is enabled; the named wrappers add visibility around non-LangGraph provider calls.

## 8. Normal maintenance commands

```powershell
# Read state
docker compose ps
docker compose logs backend --tail 200
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/datahub/catalog/cache
Invoke-RestMethod http://localhost:8000/api/v1/chat/index/status

# Apply a code or .env change
docker compose up --build -d

# Stop services but retain SQLite and Qdrant volumes
docker compose down
```

Avoid `docker compose down -v` unless you deliberately want to erase the local Qdrant index and SQLite audit trail.

## 9. Quality gates before a demonstration

```powershell
Push-Location backend
python -m pytest tests -q -p no:cacheprovider
Pop-Location

Push-Location frontend
npm run check
Pop-Location

python .\evals\runners\run_agentic_rag_evals.py
```

Run the professional acceptance plan before submission. It includes the tests that must be manually evidenced: full catalog cache, schema and lineage grounding, no-proof refusal, memory isolation, safety routing, independent judges, and optional write proof.
