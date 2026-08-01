# API reference

Base URL: `http://localhost:8000`. The generated OpenAPI contract at <http://localhost:8000/docs> is the executable source of request and response schemas. This page explains the intended safe flows.

## Runtime and DataHub reads

| Method | Route | Purpose | Side effect |
|---|---|---|---|
| `GET` | `/api/v1/health` | Non-secret configuration health | None |
| `GET` | `/api/v1/datahub/search?query=` | Read-only MCP metadata search | None |
| `GET` | `/api/v1/datahub/schema?asset_urn=` | Read-only schema lookup | None |
| `GET` | `/api/v1/datahub/lineage?asset_urn=&direction=&max_hops=` | Bounded lineage lookup | None |
| `GET` | `/api/v1/datahub/catalog/cache` | Shared 3D graph and freshness state | None |
| `POST` | `/api/v1/datahub/catalog/cache/refresh` | Request a background refresh | None |
| `GET` | `/api/v1/datahub/catalog/search` | Bounded legacy catalog projection | None |
| `GET` | `/api/v1/datahub/catalog/expand` | Bounded graph expansion | None |
| `GET` | `/api/v1/datahub/catalog/snapshot` | Paged legacy graph projection | None |

The DataHub bridge enforces a server-side allowlist. These routes cannot call write tools.

The cache response includes `refresh_in_progress`, `refresh_started_at`,
`last_updated_at`, `last_checked_at`, `generation`, `consecutive_failures`,
`last_error`, and `detected_change`. A `STALE` response with nodes means the
last complete graph is still safe to display while the worker retries.

## Impact workflow

The frontend uses grouped workflow routes. The lower-level read and planning
routes remain available for controlled API-level testing. Both judging routes
accept only a server-owned `analysis_run_id`; they do not accept a browser copy
of an impact report.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/workflows/graph` | Public workflow visualization and tracing state |
| `POST` | `/api/v1/workflows/analyze` | Build impact report and deterministic plan |
| `GET` | `/api/v1/workflows/analysis/{analysis_run_id}` | Restore an immutable server-owned read-only analysis after browser reload |
| `POST` | `/api/v1/workflows/critique` | Optional NVIDIA advisory critique |
| `POST` | `/api/v1/workflows/judge` | Reload a server-owned analysis, run Gate 0, then independent OpenAI/Groq review |
| `POST` | `/api/v1/judges/evaluate` | Lower-level equivalent using the same server-owned analysis reference |
| `GET` | `/api/v1/judges/history` | Persisted non-secret judging summaries |

The restore route accepts a UUID only. It returns the original report and plan
from SQLite but never judge results, reviewer capability, HITL state, or an
idempotency key. An unknown UUID returns `404`; a malformed value returns `422`.

Example request body:

```json
{
  "asset_urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)",
  "change_type": "ADD_COLUMN",
  "column_name": "lineageguard_demo_note",
  "reason": "Controlled LineageGuard demonstration.",
  "environment": "PRODUCTION",
  "lineage_depth": 2,
  "column_nullable": true
}
```

The result includes `analysis_run_id`, `impact_report`, `remediation_plan`, and
a public workflow graph. The plan and rollback are instructions only and remain
`NOT_EXECUTED`. Subsequent judging uses:

```json
{
  "analysis_run_id": "server-generated-analysis-id",
  "repair_cycles": 0
}
```

## Agentic RAG and MCP

| Method | Route | Purpose | Side effect |
|---|---|---|---|
| `GET` | `/api/v1/chat/index/status` | Qdrant state and `query_available` | None |
| `POST` | `/api/v1/chat/index/ingest` | Start metadata-only Qdrant ingestion | Writes Qdrant only |
| `POST` | `/api/v1/chat/query` | Agentic RAG plus live MCP verification | Read-only DataHub calls only |
| `GET` | `/api/v1/chat/memory/{session_id}` | Session memory metadata | None |
| `DELETE` | `/api/v1/chat/memory/{session_id}` | Erase session memory | Deletes local memory only |
| `POST` | `/api/v1/chat/execute-analysis` | Confirmed handoff to impact workflow | Read-only DataHub calls only |

Example query:

```json
{
  "message": "What is the schema of the Snowflake orders dataset?",
  "session_id": "browser-generated-random-id",
  "memory_enabled": true
}
```

| Response field | Meaning |
|---|---|
| `target_resolution` | Exact target selection, ambiguity, no match, or no target needed |
| `citations` | RAG candidates and/or MCP-verified citations |
| `evidence` | Named evidence records used by the verifier |
| `verification` | Deterministic result, blocking issues, per-claim evidence IDs/reasons, supported/total counts, and `claim_coverage` |
| `action_proposal` | `NONE`, `ANALYZE_IMPACT`, or `HITL_WRITEBACK` |
| `agent_trace` | Public execution trace, never private reasoning |
| `model_usage` | Safe token/cost telemetry when available |

An index can be `RUNNING` while `query_available=true`: the active Qdrant alias keeps the prior complete snapshot usable while a replacement is built. A validated alias switch publishes the new snapshot atomically and removes records that disappeared from DataHub.

`POST /api/v1/chat/query` also has a whole-request deadline configured by
`CHAT_TOTAL_TIMEOUT_SECONDS`. Expiry cancels the graph and outstanding MCP work
and returns `504`; it never authorizes a target handoff or action proposal.

When an `ANALYZE_IMPACT` response resolves exactly one live MCP target, it also
returns `analysis_handoff_id` and `analysis_handoff_expires_at`. The frontend
must send that ID, the same `session_id`, and the exact resolved asset URN to
`/chat/execute-analysis`. The server rejects expired, cross-session, or
substituted targets with `409`. A newer resolution revokes the older handoff.

The change form supports `ADD_COLUMN`, `RENAME_COLUMN`,
`CHANGE_COLUMN_TYPE`, and `DROP_COLUMN`. Every type requires a column;
rename/type changes additionally require `new_value`. Type-specific fields are
not sent for unrelated change types.

Validation is evidence-bound and case-insensitive: `ADD_COLUMN` rejects an
existing field, `RENAME_COLUMN` rejects an identical or existing target, and
`CHANGE_COLUMN_TYPE` rejects a missing current type or a target type equivalent
to the current type after case/whitespace normalization. Multi-hop impacts are
accepted only when `get_lineage_paths_between` supplies an exact, acyclic path
whose hop count matches the original lineage result.

## HITL document write-back

| Method | Route | Rule |
|---|---|---|
| `POST` | `/api/v1/writebacks/prepare` | Requires enabled write-back, local reviewer capability, server-owned double-PASS run, and idempotency key |
| `GET` | `/api/v1/writebacks/{run_id}` | Read proposal and immutable snapshot |
| `GET` | `/api/v1/writebacks/{run_id}/audit` | Read ordered audit events |
| `POST` | `/api/v1/writebacks/{run_id}/approve` | Human approval, revision, or rejection |
| `POST` | `/api/v1/writebacks/{run_id}/rollback` | Separate approval to supersede a completed document |
| `POST` | `/api/v1/writebacks/{run_id}/reconcile` | Resolve an uncertain create after live DataHub verification |

The sole write action is `save_document` for an Analysis document. All POST
routes above require `X-LineageGuard-Reviewer-Capability`; the server compares
it in constant time with `LOCAL_REVIEWER_CAPABILITY`. When
`DATAHUB_WRITEBACK_ENABLED=false`, even proposal preparation fails with an
explicit `503` before workflow state changes. A missing or weak server
capability also returns `503`; a missing or incorrect header returns `403`.
Proposal responses deliberately omit the idempotency key. The client that
prepared the proposal must retain that key for subsequent human decisions.

Concurrent approval requests are serialized with a durable compare-and-swap;
only one caller may invoke DataHub. An ambiguous remote result returns
`WRITEBACK_UNCERTAIN` and blocks automatic retries. Reconciliation either
adopts a document whose title and related asset are reverified through MCP, or
records an explicit human confirmation that no document exists. Compensation
operates only on the persisted document URN. See
[Secure HITL write-back](hitl-writeback.md).

`REQUEST_REVISION` closes the old proposal as `REVISION_REQUESTED`. The UI
restores the exact reviewed request and reviewer comment, discards the old
analysis/judge/write-back state, and requires at least one request change before
a fresh analysis. The revised report must pass all gates again.

## HTTP behaviour

- `200` / `202`: normal read or accepted background operation.
- `409`: concurrent operation, immutable idempotency conflict, or uncertain
  external outcome that requires reconciliation.
- `403`: the local reviewer capability is missing or invalid.
- `422`: validation failed or explicit confirmation is missing.
- `503`: DataHub, Qdrant, or optional provider configuration is unavailable.
- `504`: the bounded chat request deadline expired and work was cancelled.
- `500`: unexpected server condition; inspect backend logs without copying secrets.

Use `/docs` for exact Pydantic contracts rather than reconstructing full request and response objects from this overview.
