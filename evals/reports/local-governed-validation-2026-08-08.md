# Local governed functionality validation — 2026-08-08

This is a dated **local smoke validation**, not a replacement for the reviewed
30-query benchmark or its ranking metrics. It records the implementation
checks performed against the local Docker/DataHub environment after the
reliability fixes.

## Automated checks

| Check | Result | Scope |
|---|---:|---|
| Targeted backend suite | PASS | 99 tests across chat target resolution, catalog cache, judging, and write-back |
| Frontend quality gate | PASS | 23 Vitest tests, TypeScript compilation, and Vite production build |
| Write-back post-verification unit | PASS | Verifies the exact Analysis document as related to the governed target asset |

## Browser checks

| Scenario | Result | Evidence observed |
|---|---:|---|
| Ambiguous `orders` lineage selection | VERIFIED | Selecting `ORDERS · snowflake` replayed the original question with the selected URN; live `get_lineage` returned two direct relationships with target-owned evidence. |
| Snowflake schema answer | VERIFIED | 15 fields and 16 factual claims were shown as 16/16 supported by live MCP schema evidence. |
| Catalog cache | PASS | The server cache remained visible while enrichment ran. Once ready, it showed 1,194 assets and 1,174 relationships with no fatal timeout banner. |
| Double-judge positive case | PASS / PASS | Nullable `ADD_COLUMN` produced OpenAI PASS and Groq PASS. |
| Independent disagreement | PASS / FAIL | `DROP_COLUMN order_id` produced OpenAI PASS and Groq FAIL. Groq identified high-criticality downstream consumers and required migration evidence. |
| Double refusal | FAIL / FAIL | `CHANGE_COLUMN_TYPE order_id → BOOLEAN` marked incompatible was rejected by both judges; both cited missing downstream remediation. |
| HITL document-only mutation | COMPLETED → ROLLED_BACK | The integrated confirmation was shown in-page, the Analysis document was post-write verified from the target asset, then compensation completed. No schema or warehouse data mutation was attempted. |

## What this does and does not prove

- It proves the current local control flow, target locking, provider outcome
  presentation, and document-only HITL path.
- It does **not** establish fresh retrieval-quality metrics, provider cost, or
  latency percentiles. Those remain attributable only to the reviewed dated
  professional benchmark.
- Provider outcomes are intentionally scenario-dependent. A PASS is not
  automatic approval: the Groq technical/safety role can reject an otherwise
  grounded report, and either judge can fail closed on incompatible changes.
