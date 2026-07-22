# Final evaluation report

Generated: 2026-07-20  
Dataset: `lineageguard-eval-v1`  
Mode: offline deterministic contract and coverage evaluation (no live DataHub or provider call)

## Environment

| Component | Reference |
|---|---|
| API | FastAPI application in this repository |
| Metadata system | Local DataHub Core, measured separately |
| Advisory critic | NVIDIA Build, not called by this runner |
| Final judges | OpenAI and Groq, mocked in CI and measured separately |

## Dataset coverage

| Change type | Cases |
|---|---:|
| ADD_COLUMN | 5 |
| CHANGE_COLUMN_TYPE | 5 |
| DROP_COLUMN | 5 |
| RENAME_COLUMN | 5 |

All 20 reference cases are structurally valid and cover: complete/no lineage, invalid asset/column, missing owners/platform, multi-hop, cross-platform, prompt injection, provider timeout, judge disagreement and write-back failure.

## Offline results

| Metric | Result | Interpretation |
|---|---:|---|
| Dataset contract coverage | 20 / 20 | All required cases and tags are present |
| Change-type coverage | 5 / 5 each | All four change types are represented equally |
| Deterministic score reproducibility | validated by unit tests | No provider call is involved |
| Evidence-reference validation | validated by unit tests | Invalid evidence blocks Gate 0 |
| Mutation idempotence / compensation | validated by unit tests | Uses a fake writer and SQLite fixture |
| Live asset precision / recall | not measured | Requires a reviewed live DataHub reference run |
| OpenAI/Groq agreement | not measured | Requires an explicitly authorized live provider run |
| End-to-end write-back success | not measured | Requires a dedicated disposable DataHub environment |

## Required manual pre-submission run

1. Start local DataHub and load the showcase dataset.
2. Select at least one reviewed asset for each change type.
3. Record real downstream assets and lineage paths in the dataset ground truth after manual review.
4. Run the UI workflow with explicit consent for NVIDIA, OpenAI and Groq calls.
5. Record provider agreement, latency and outcomes; never record API keys.
6. Keep `DATAHUB_WRITEBACK_ENABLED=false` unless a disposable demo environment and a human reviewer are present.

## Known limitations

- This report is a reproducible offline baseline, not a claim of live-provider accuracy.
- Current local DataHub sample metadata may not contain every business contract required to prove compatibility.
- The only supported write-back is an approved analysis document; warehouse, dbt and schema mutations are deliberately out of scope.
- A double PASS is necessary but never sufficient to bypass human approval.

## Agentic RAG companion baseline

The separate [Agentic RAG + MCP fixture baseline](agentic-rag-baseline.md)
measures retrieval precision/recall, schema exact match, lineage coverage,
tool selection, evidence citations, verifier blocking, latency and estimated
cost. Its scores are offline fixture measurements only; a dated live benchmark
with reviewed DataHub ground truth is still required before publishing any live
quality claim.
