# P0 correctness validation — 2026-08-01

## Scope

This run validates three blocking correctness invariants against the local
`showcase-ecommerce` DataHub catalog:

1. Qdrant guides bounded candidate discovery, while DataHub MCP remains the
   only authority that can confirm an exact URN.
2. Multi-hop impacts contain the exact MCP path rather than a fabricated
   source/target shortcut.
3. Duplicate adds, rename collisions, and unchanged type requests fail before
   lineage traversal, judging, or any action proposal.

No DataHub mutation was enabled or executed during this run.

## Automated validation

| Check | Result |
|---|---:|
| Backend tests collected | 141 |
| Backend tests passed | 137 |
| Explicit live/write-back tests skipped by default | 4 |
| Frontend Vitest tests | 11/11 passed |
| TypeScript build | Passed |
| Vite production build | Passed |
| `git diff --check` | Passed |

The focused adversarial tests cover stale and weak Qdrant candidates, a
bounded three-candidate fan-out, schema-field parent projection, ambiguous
vector scores, target locking, cyclic/incomplete paths, case-insensitive field
collisions, missing current types, same-type requests, and Gate 0 path
tampering.

## Live DataHub and Qdrant results

Environment observed during the final run:

- LineageGuard API: healthy on `http://localhost:8000`
- DataHub GMS: healthy on `http://localhost:8080`
- Qdrant: healthy with 1,190 indexed metadata assets
- DataHub catalog: 1,191 live root assets observed

### Exact schema proof

Question: `What is the schema of the Snowflake orders dataset?`

- target: exact Snowflake `orders` URN
- target status: `RESOLVED`
- verifier: `PASSED`
- claim support: 16/16 factual claims
- MCP tools: `search`, `list_schema_fields`
- Qdrant substitutions: 0

### Hybrid retrieval proof

Question: `What is the schema of the customer order transactions table?`

- Qdrant records retrieved: 12
- Qdrant-guided candidates rediscovered with the exact URN by MCP: 3
- result: `AMBIGUOUS`
- schema calls: 0

This is an intentional safe outcome. Several close candidates were live, but
none exceeded the configured score margin, so vector rank did not silently
choose a platform or dataset.

### Multi-hop impact proof

Request: read-only `DROP_COLUMN order_status` analysis for the showcase dbt
`orders` dataset with `lineage_depth=3`.

| Metric | Result |
|---|---:|
| End-to-end latency | 33.1 s |
| Blast radius | 36 assets |
| Exact multi-hop paths | 35 |
| Maximum path size | 7 nodes |
| `get_lineage_paths_between` evidence records | 35 |

Every multi-hop item was expanded and evidence-bound. Unit tests additionally
prove that incomplete, cyclic, wrong-endpoint, wrong-hop-count, and Gate 0
tampered paths fail closed.

### Invalid change contracts

All requests used the live Snowflake `orders` schema and returned HTTP `422`
without producing an impact report:

| Case | Live result | Latency |
|---|---|---:|
| `ADD_COLUMN ORDER_ID` when `order_id` exists | Rejected as duplicate | 12.15 s cold |
| Rename `order_id` to existing `customer_id` | Rejected as collision | 3.61 s |
| Change `order_id` from `NUMBER(38,0)` to `number(38, 0)` | Rejected as unchanged type | 3.67 s |

## Devil's-advocate findings addressed

- A Qdrant score threshold of `0.65` was too high for observed OpenAI cosine
  scores (`0.45–0.58`) and would have made the hybrid path mostly inert. The
  default is now `0.40`, with exact MCP rediscovery and a separate `0.05`
  dominance margin.
- Schema queries often retrieve schema fields before datasets. Their explicit
  parent dataset URNs are now deduplicated and live-confirmed instead of being
  discarded or treated directly as schema targets.
- Qdrant client `1.18` warned about the Qdrant server `1.15.5`. The client is
  now constrained to `>=1.15,<1.17`; the rebuilt container uses `1.16.2`.
- Invalid schema changes previously fetched lineage before rejection. They now
  stop after the source schema check.
- One immediate repeated live analysis timed out while the server-owned 3D
  cache was enriching lineage. The isolated rerun passed in 33.1 seconds under
  the 45-second MCP deadline. This is recorded as an operational contention
  observation; it did not produce partial evidence or authorize an action.
