# Local validation record — 2026-07-20

This is an execution record for the local development environment. It complements the offline baseline in [`final-evaluation.md`](final-evaluation.md); it does not inflate provider-quality claims.

## Executed checks

| Check | Result | Evidence |
|---|---:|---|
| Offline evaluation dataset runner | PASS | 20 manually curated cases, five per supported change type |
| Backend unit, integration-mock, security and workflow tests | PASS | `34 passed, 3 skipped` |
| Local DataHub read-only integration suite | PASS | `3 passed` against local GMS |
| Frontend type check and production build | PASS | `tsc -b && vite build` |

## Scope of the successful DataHub integration

The three integration tests exercised the read-only MCP/DataHub path against the local GMS service. They do not create, alter, or delete metadata.

## Deliberately unmeasured metrics

- Live NVIDIA/OpenAI/Groq judge agreement and latency were not run automatically, so that the evaluation remains cost-controlled and requires an explicit human choice.
- Live write-back success was not measured: write-back stays disabled by default and must be tested only in a disposable DataHub environment after HITL approval.
- Asset-level precision and recall require a reviewed, environment-specific lineage reference set; the offline dataset is a coverage baseline, not a substitute for that review.

## Reproduction

```powershell
# Repository root
python .\evals\runners\run_deterministic_evals.py

# Backend
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests

# DataHub integration (requires the local GMS service)
$env:RUN_DATAHUB_INTEGRATION = '1'
$env:PYTHONPATH = (Resolve-Path .).Path
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\integration

# Frontend
Set-Location ..\frontend
npm run check
```
