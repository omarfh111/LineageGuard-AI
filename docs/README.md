# Documentation map

Start with the repository [README](../README.md) for a concise overview and quick start. Use this directory for implementation and operating detail.

| Document | Status | Scope |
|---|---|---|
| [Architecture](architecture.md) | Current | Components, trust boundaries, diagrams, cache lifecycle, and agent invariants |
| [Runbook](runbook.md) | Current | Local installation, configuration, demo, tracing, and operating commands |
| [API reference](api-reference.md) | Current | Current API routes and safe request flows |
| [Agentic RAG + MCP](agentic-rag.md) | Current | Qdrant, target locking, verification, memory, and routing |
| [DataHub local](datahub-local.md) | Current | Local Quickstart and showcase datapack |
| [Impact analysis](impact-analysis.md) | Current | Deterministic risk and evidence model |
| [Remediation and rollback](remediation-and-rollback.md) | Current | Non-executable plans and business compensation |
| [Independent judging](double-judging.md) | Current | Gate 0, provider roles, fallback, and aggregation |
| [HITL write-back](hitl-writeback.md) | Current | Document-only mutation, idempotency, audit, and compensation |
| [Live write proof](live-writeback-proof.md) | Opt-in | Disposable-environment real DataHub document proof |
| [Troubleshooting](troubleshooting.md) | Current | Operations and failure diagnosis |
| [Acceptance test plan](acceptance-test-plan.md) | Current | Professional pre-submission test protocol |
| [Phase 0 bootstrap](phase-0-bootstrap.md) | Historical | Original bootstrap scope and deferrals |

The dated reports under [`../evals/reports/`](../evals/reports/) are historical evidence. They must not be silently rewritten as current live-performance claims; record any new benchmark as a new dated report with its dataset, model, environment, and reviewer ground truth.
