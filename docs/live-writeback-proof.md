# Live DataHub write-back proof

The default application is read-only. The only permitted mutation is an
approved **DataHub Analysis document**; LineageGuard never changes a warehouse
schema, dataset, lineage edge, dbt model, or BI dashboard.

This repository contains an opt-in integration proof at
`backend/tests/integration/test_live_writeback_proof.py`. It performs the
following auditable sequence against a disposable/local DataHub environment:

```mermaid
sequenceDiagram
  participant H as Human reviewer
  participant L as LineageGuard
  participant M as DataHub MCP
  participant D as DataHub
  H->>L: Explicit environment confirmation
  par Approval A
    L->>L: Atomic compare-and-swap
  and Approval B
    L->>L: Atomic compare-and-swap
  end
  L->>M: exactly one save_document call (Analysis only)
  M->>D: Create Analysis document
  D-->>L: document URN
  par Rollback A
    L->>L: Atomic compare-and-swap
  and Rollback B
    L->>L: Atomic compare-and-swap
  end
  L->>M: exactly one save_document call (same URN)
  M->>D: Supersede proof document
  L-->>H: Audit events and final ROLLED_BACK status
```

## Preconditions

1. Start the local DataHub Quickstart and LineageGuard services.
2. Ensure the catalog contains at least one dataset.
3. In the shell **only for this disposable proof**, set:

```powershell
$env:RUN_DATAHUB_WRITEBACK_PROOF = "1"
$env:CONFIRM_LIVE_WRITEBACK = "I_APPROVE_DEMO_DOCUMENT"
$env:DATAHUB_WRITEBACK_ENABLED = "true"
$env:DATAHUB_GMS_URL = "http://localhost:8080"
```

4. From `backend`, run:

```powershell
python -m pytest tests/integration/test_live_writeback_proof.py -q -p no:cacheprovider
```

The command deliberately creates and then supersedes one document. It submits
two concurrent approvals and two concurrent compensations, asserting one writer
call in each case. Capture the terminal output plus the document URN/audit trail
for the submission evidence.
After the proof, unset `DATAHUB_WRITEBACK_ENABLED` or restore it to `false`.

The proof uses a synthetic deterministic PASS packet so it measures the live
MCP write and compensation path only. Judge quality remains measured separately
by the evaluation harness.

## Full governed workflow runner

For a proof that includes real analysis and both configured judges before HITL,
run the gate-only form first:

```powershell
python .\evals\runners\run_live_governed_writeback.py
```

This performs no mutation. In an explicitly approved disposable environment,
enable `DATAHUB_WRITEBACK_ENABLED=true` for that backend instance and run:

```powershell
python .\evals\runners\run_live_governed_writeback.py --execute
```

The runner requires deterministic PASS, OpenAI PASS, Groq PASS, and aggregate
`FINALIZE_READ_ONLY`; then it prepares an idempotent proposal, approves it,
verifies `COMPLETED`, compensates the same persisted document URN, verifies
`ROLLED_BACK`, and checks the exact six-event audit sequence. Compensation
supersedes the Analysis document; it does not erase audit history.

The reviewed 2026-07-31 execution and non-secret artifact identifiers are in
[`../evals/reports/professional-validation-2026-07-31.md`](../evals/reports/professional-validation-2026-07-31.md).
