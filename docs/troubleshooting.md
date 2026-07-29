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

## 3D catalog stays on RUNNING

At a backend restart, `RUNNING` is normal only until the bounded root catalog loads. Once assets are available, the status should change to `READY` with a message that lineage relationships are still enriching. The graph remains usable during enrichment.

If the status repeatedly returns to a full refresh after it reached `READY`:

1. Save the cache JSON and the `refresh_reason` field.
2. Verify the backend image was rebuilt after the cache reliability update.
3. Check that `CATALOG_MAX_ASSETS` is large enough for the local catalog.
4. Check backend logs for DataHub MCP errors.

The server detects external changes by polling root URNs; it intentionally does not use browser page load as a refresh trigger.

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
2. Prefer a faster available model for a demo if the chosen large model repeatedly times out.
3. Confirm `NVIDIA_TIMEOUT_SECONDS` is appropriate for the model.
4. Retry once later; do not treat a failed advisory call as a passing review.

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

Read proposal and audit data with:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>"
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>/audit"
```

Keep `DATAHUB_WRITEBACK_ENABLED=false` for ordinary hackathon demonstrations. Use the dedicated disposable proof only when you explicitly intend to create and supersede a demo Analysis document.
