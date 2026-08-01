# Professional validation — 2026-07-31

## Verdict

**PASS.** The final isolated live run completed all 30 reviewed Agentic RAG cases and passed every configured professional threshold. A separate governed write proof completed the full analyze → double judge → HITL → DataHub document write-back → compensation lifecycle.

This report records live local results, not mocked or offline substitutes. Provider credentials and raw secrets are excluded.

## Environment and methodology

- DataHub: local `showcase-ecommerce` metadata graph, queried through the read-only DataHub MCP server.
- Retrieval: existing stale-free Qdrant snapshot containing 1,190 metadata entities.
- Dataset: [`professional-agentic-rag-v1.json`](../datasets/professional-agentic-rag-v1.json), reviewed on 2026-07-31.
- Cases: 30 isolated requests; conversation memory disabled; 22 have exact relevant-URN ranking labels.
- Coverage: multi-platform catalog discovery, exact platform filtering, schema, downstream lineage, nonexistent assets, and ambiguous targets.
- Evaluation model usage: `gpt-4.1-mini` for adaptive planning; structured MCP facts use deterministic rendering and deterministic claim verification.
- Isolation: a disposable API instance on port 8001 with `CATALOG_AUTOLOAD=false`, preventing 3D catalog traversal from contending with the measured MCP requests.

## Agentic RAG metrics

| Metric | Result |
|---|---:|
| Completed cases | 30 / 30 |
| Reviewed ranking cases | 22 |
| Precision@6 | 0.992 |
| Recall@6 | 1.000 |
| MRR@6 | 1.000 |
| NDCG@6 | 1.000 |
| Result diversity@6 | 0.844 |
| Router accuracy | 1.000 |
| Tool-selection accuracy | 1.000 |
| Verification accuracy | 1.000 |
| Target-resolution accuracy | 1.000 |
| Verified citation coverage | 1.000 |
| Unsupported-claim block rate | 1.000 |
| Unsupported-claim escape rate | 0.000 |
| Fully supported verified-answer rate | 1.000 |
| Mean latency | 6,913.8 ms |
| p50 latency | 5,943.2 ms |
| p95 latency | 9,869.4 ms |
| Total measured tokens | 4,733 |
| Estimated OpenAI cost | USD 0.0040112 |

`claim_support_coverage` is 0.963 across all extracted claim records because safe nonexistent/ambiguous limitations deliberately contain no evidence-backed positive claim. No unsupported claim was released as a verified answer.

All strict gates in `run_live_agentic_evals.py` passed: ≥20 reviewed ranking cases, all cases completed, ranking thresholds, exact routing/tool/verification/target results, and zero unsupported-claim escape.

## Failure-driven fixes validated by the run

The first sustained run exposed a target-list alias: adding downstream citations mutated the resolved target list, so a retry recursively queried descendants. The fix copies the target lock before expanding citations and is covered by a regression test. A server-wide 75-second request deadline now cancels abandoned MCP work. Structured catalog/schema/lineage facts are rendered without model paraphrase, and every sentence has its own evidence scope.

The final run followed these corrections and reduced p95 from the failed run's 120-second ceiling to 9.87 seconds.

## Governed live write-back proof

The proof used a non-mutating proposal to rename `order_status` to `order_status_code` on the Snowflake `orders` dataset in STAGING. LineageGuard did **not** execute that schema change; its sole mutation was a compensable DataHub Analysis document.

| Gate or artifact | Result |
|---|---|
| Analysis run | `bc56525e-e707-42de-967f-185ec73c9f03` |
| Evidence | 15 source fields; 2 direct downstream assets |
| Risk | 36 / MEDIUM |
| Judging run | `a40e8cea-76d2-4247-ab3d-6bd23032f29b` |
| Deterministic gate | PASS |
| OpenAI judge | PASS |
| Groq judge | PASS |
| Aggregate decision | `FINALIZE_READ_ONLY` |
| Write-back proposal | `9d4e799b-dc0b-4ea9-958a-cfbb6a5a5b6e` |
| Created document | `urn:li:document:shared-b59945cb-8026-496a-a504-66723763fac6` |
| Write result | `COMPLETED` |
| Compensation result | `ROLLED_BACK` |
| Compensation error | none |

The durable audit sequence was exactly:

1. `WRITEBACK_PREPARED`
2. `APPROVED`
3. `WRITEBACK_PENDING`
4. `WRITEBACK_COMPLETED`
5. `ROLLBACK_PENDING`
6. `ROLLBACK_COMPLETED`

Compensation supersedes the analysis document in place; it does not pretend that an external write never occurred. Normal operation remains read-only with `DATAHUB_WRITEBACK_ENABLED=false`.

## Reproduce

Read-only professional Agentic RAG run:

```powershell
python .\evals\runners\run_live_agentic_evals.py --timeout-seconds 85
```

Gate-only governed workflow (no mutation):

```powershell
python .\evals\runners\run_live_governed_writeback.py
```

Disposable live document proof, only after explicitly enabling write-back:

```powershell
python .\evals\runners\run_live_governed_writeback.py --execute
```

The opt-in runner refuses mutation unless deterministic validation, OpenAI, and Groq all PASS. It performs one bounded idempotent compensation retry and fails loudly with the proposal ID if manual reconciliation is required.
