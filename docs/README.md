# Documentation map

Start with the repository [README](../README.md) for a concise overview and quick start. Use this directory for implementation and operating detail.

| Document | Status | Scope |
|---|---|---|
| [Architecture](architecture.md) | Current | Components, trust boundaries, diagrams, cache lifecycle, and agent invariants |
| [Runbook](runbook.md) | Current | Local installation, configuration, demo, tracing, and operating commands |
| [Submission checklist](submission-checklist.md) | Current | Devpost requirements, release gate, public-access checks, description, and under-three-minute video storyboard |
| [Problem and resolution log](problem-resolution-log.md) | Current | Symptoms, root causes, implemented fixes, validation, and residual risk |
| [Five-minute live demo](five-minute-demo.md) | Current | Longer operator/judge walkthrough and safe provider fallbacks |
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

## Evidence labels

- **Current** describes code and operating behavior in the repository.
- **Opt-in** requires an explicit external provider or disposable DataHub action.
- **Historical** preserves the scope and result of an earlier milestone.
- A **configured** provider has enough non-secret runtime configuration to try a
  request; only a dated successful request is live evidence.
- Offline metrics validate deterministic contracts and ranking fixtures. They
  are not substitutes for reviewed live DataHub/model results.

For the final release, start with the [submission checklist](submission-checklist.md),
then execute the [acceptance test plan](acceptance-test-plan.md) against the
exact commit that will be pushed.
