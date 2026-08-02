# Troubleshooting

Never paste a key, `.env` content, raw provider authorization header, or unreviewed trace input into an issue or screenshot.

## First checks

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/datahub/catalog/cache
Invoke-RestMethod http://localhost:8000/api/v1/chat/index/status
docker compose logs backend --tail 200
```

After a code or `.env` change:

```powershell
docker compose up --build -d
```

## Docker Desktop is not running

Confirm that Docker Desktop shows **Engine running**. If it reports missing virtualization, enable virtualization in BIOS/UEFI or contact the device administrator. This project uses the Linux engine over WSL 2 and does not require Windows containers.

## DataHub is unavailable or no assets appear

| Symptom | Likely cause | Action |
|---|---|---|
| `DATAHUB_GMS_URL is not configured` | Missing or incorrect URL | Use `host.docker.internal:8080` in Docker; use `localhost:8080` outside Docker |
| Token configuration error | Non-local DataHub without token | Create a DataHub token and put it only in `.env` |
| No DataHub UI on port 9002 | Quickstart stopped | Run `./scripts/start-datahub.ps1` |
| Empty catalog or missing sample asset | Datapack not loaded | Run `./scripts/load-showcase-data.ps1` |

If `start-datahub.ps1` reports that `datahub-gms-quickstart` is unhealthy, do
not start LineageGuard against the half-ready stack. Inspect the GMS logs and
the dependency health first:

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
docker logs datahub-datahub-gms-quickstart-1 --tail 200
docker logs datahub-mysql-1 --tail 100
docker logs datahub-opensearch-1 --tail 100
docker logs datahub-kafka-broker-1 --tail 100
```

Common causes are insufficient Docker memory, an interrupted first-time image
or migration startup, and unhealthy MySQL/OpenSearch/Kafka dependencies. Fix
the dependency, rerun `start-datahub.ps1`, and require a healthy GMS rather
than bypassing the script's safety check.

## 3D catalog stays on RUNNING

At a backend restart, `RUNNING` is normal only until the bounded root catalog loads. Once assets are available, the status should change to `READY` with a message that lineage relationships are still enriching. The graph remains usable during enrichment.

If the status repeatedly returns to a full refresh after it reached `READY`:

1. Save the cache JSON, including `refresh_reason`, `generation`,
   `consecutive_failures`, `last_error`, and `last_checked_at`.
2. Verify the backend image was rebuilt after the cache reliability update.
3. Check that `CATALOG_MAX_ASSETS` is large enough for the local catalog.
4. Check backend logs for DataHub MCP errors.

The server detects root membership/metadata changes and performs rotating exact
schema/lineage probes. A schema or lineage change may therefore take up to
`ceil(asset_count / CATALOG_CHANGE_PROBE_ASSETS)` polling cycles to be seen.
Browser page load never triggers a refresh.

If `last_error` reports the refresh watchdog, do not increase concurrency.
First verify DataHub GMS health, then tune `DATAHUB_MCP_TIMEOUT_SECONDS` and
`CATALOG_REFRESH_TIMEOUT_SECONDS`. The previous graph remains available and
the worker retries automatically.

## Filters do not show the full graph again

Clear the search text and set both filters to `All`. The UI filters the server-cached full graph locally, so the complete view is restored without another DataHub fetch. If it does not, hard-refresh the browser after rebuilding the frontend.

## Chat is disabled during indexing

The first index must complete before querying. During a subsequent re-index, `/api/v1/chat/index/status` should report `query_available: true`; the UI should display `CHAT READY · INDEXING` and remain usable. If it does not, verify the existing Qdrant collection and rebuild backend/frontend.

## Chat response is LIMITED

`LIMITED` is a safe outcome, not necessarily a bug. Inspect the target-resolution card and technical trace:

- `AMBIGUOUS`: provide a platform or exact URN.
- `NOT_FOUND`: correct the requested asset; schema and lineage tools intentionally were not run.
- Missing schema/lineage evidence: verify the asset exists in DataHub and the target has that metadata.
- Missing cited evidence ID: the verifier rejected an otherwise plausible answer.

Clear memory before independent test cases. Normal six-turn memory helps conversational follow-ups but must not be used to claim independent evaluation results.

## NVIDIA advisory critic times out

The advisory critic is bounded to a compact dossier and a maximum response size. A timeout is surfaced explicitly and cannot change the remediation plan.

1. Confirm the configured model is available to the NVIDIA account.
2. Use `NVIDIA_CRITIC_MODEL=nvidia/nemotron-3-nano-30b-a3b` for the interactive demo. It passed the repository's live contract test in 2.92 seconds on 2026-08-01.
3. Confirm `NVIDIA_TIMEOUT_SECONDS` is appropriate for the model.
4. Retry once later; do not treat a failed advisory call as a passing review.

Do not use `z-ai/glm-5.2` as the interactive critic on the shared endpoint unless
a rehearsal succeeds: two live attempts timed out at 90 seconds even with
reasoning disabled and streaming enabled. It can remain the worker model.
Model availability also changes: query the NVIDIA account rather than trusting
an old model name. The previously documented Qwen critic endpoints returned
HTTP 410 during the 2026-08-01 validation.

NVIDIA’s endpoint is OpenAI-compatible; the expected base URL is `https://integrate.api.nvidia.com/v1` ([NVIDIA API reference](https://docs.api.nvidia.com/nim/reference/llm-apis)).

## OpenAI or Groq judge is unavailable

An unavailable judge never becomes PASS. One unavailable judge produces `AWAITING_HUMAN`; two produce `BLOCKED`.

1. Check backend logs for the safe error type, not the key.
2. Confirm the model name is enabled in the provider account and quota is available.
3. Keep `JUDGE_MAX_RETRIES` bounded to control cost.
4. Groq first attempts strict JSON Schema then JSON-object mode; a provider outage, rate limit, or invalid response after this fallback still remains unavailable.

## Write-back is refused

| Message or state | Meaning |
|---|---|
| `DATAHUB_WRITEBACK_ENABLED is false` | Normal protection; no write was attempted |
| Prepare request rejected | Gate 0 or double PASS is absent |
| `Unknown server-owned judging run` | Invalid or non-persistent run ID |
| `FAILED` | Document write was attempted only after approval and failed; inspect the audit trail |
| `reviewer_unconfigured` | Feature flag is enabled but the running backend did not receive a 24+ character server capability |
| `A valid local reviewer capability is required` | The tab value is missing/different, or the backend was not recreated after `.env` changed |

Read proposal and audit data with:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>"
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>/audit"
```

Keep `DATAHUB_WRITEBACK_ENABLED=false` for ordinary hackathon demonstrations. Use the dedicated disposable proof only when you explicitly intend to create and supersede a demo Analysis document.

For the isolated proof, set only:

```env
DATAHUB_WRITEBACK_ENABLED=true
LOCAL_REVIEWER_CAPABILITY=<same random 24+ character value entered in the UI>
```

Then run `docker compose up --build -d backend`, verify
`/api/v1/health` reports `writeback: ready`, and enter the exact same value in
the current browser tab. Do **not** globally enable
`DATAHUB_MUTATIONS_ENABLED` or `TOOLS_IS_MUTATION_ENABLED`; the normal MCP
server must stay read-only.

## Local test process or temporary-directory errors

`spawn EPERM` from Vite/esbuild or `PermissionError` under a Windows pytest
temporary directory is an execution-environment restriction, not a passing or
failing application assertion. Close processes locking the directory and rerun
from a normal PowerShell terminal. If pytest's default temp root is locked, use
an explicit newly created writable base directory outside a synchronized or
protected folder, then remove it after the run. Do not record an infrastructure
error as a test failure, and do not claim PASS until the same command completes
normally.
