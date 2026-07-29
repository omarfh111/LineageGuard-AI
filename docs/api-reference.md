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

## Impact workflow

The frontend uses grouped workflow routes. The lower-level read and planning
routes remain available for controlled API-level testing. Both judging routes
accept only a server-owned `analysis_run_id`; they do not accept a browser copy
of an impact report.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/workflows/graph` | Public workflow visualization and tracing state |
| `POST` | `/api/v1/workflows/analyze` | Build impact report and deterministic plan |
| `POST` | `/api/v1/workflows/critique` | Optional NVIDIA advisory critique |
| `POST` | `/api/v1/workflows/judge` | Reload a server-owned analysis, run Gate 0, then independent OpenAI/Groq review |
| `POST` | `/api/v1/judges/evaluate` | Lower-level equivalent using the same server-owned analysis reference |
| `GET` | `/api/v1/judges/history` | Persisted non-secret judging summaries |

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
| `verification` | Deterministic validation result and blocking issues |
| `action_proposal` | `NONE`, `ANALYZE_IMPACT`, or `HITL_WRITEBACK` |
| `agent_trace` | Public execution trace, never private reasoning |
| `model_usage` | Safe token/cost telemetry when available |

An index can be `RUNNING` while `query_available=true`: a prior Qdrant collection is usable and the chat should remain available during re-indexing.

## HITL document write-back

| Method | Route | Rule |
|---|---|---|
| `POST` | `/api/v1/writebacks/prepare` | Requires a server-owned double-PASS judging run and idempotency key |
| `GET` | `/api/v1/writebacks/{run_id}` | Read proposal and immutable snapshot |
| `GET` | `/api/v1/writebacks/{run_id}/audit` | Read ordered audit events |
| `POST` | `/api/v1/writebacks/{run_id}/approve` | Human approval, revision, or rejection |
| `POST` | `/api/v1/writebacks/{run_id}/rollback` | Separate approval to supersede a completed document |
| `POST` | `/api/v1/writebacks/{run_id}/reconcile` | Resolve an uncertain create after live DataHub verification |

The sole write action is `save_document` for an Analysis document. An approval
fails safely when `DATAHUB_WRITEBACK_ENABLED=false`; it does not silently
change DataHub. Proposal responses deliberately omit the idempotency key. The
client that prepared the proposal must retain that key for subsequent human
decisions.

Concurrent approval requests are serialized with a durable compare-and-swap;
only one caller may invoke DataHub. An ambiguous remote result returns
`WRITEBACK_UNCERTAIN` and blocks automatic retries. Reconciliation either
adopts a document whose title and related asset are reverified through MCP, or
records an explicit human confirmation that no document exists. Compensation
operates only on the persisted document URN. See
[Secure HITL write-back](hitl-writeback.md).

## HTTP behaviour

- `200` / `202`: normal read or accepted background operation.
- `409`: concurrent operation, immutable idempotency conflict, or uncertain
  external outcome that requires reconciliation.
- `422`: validation failed or explicit confirmation is missing.
- `503`: DataHub, Qdrant, or optional provider configuration is unavailable.
- `500`: unexpected server condition; inspect backend logs without copying secrets.

Use `/docs` for exact Pydantic contracts rather than reconstructing full request and response objects from this overview.
