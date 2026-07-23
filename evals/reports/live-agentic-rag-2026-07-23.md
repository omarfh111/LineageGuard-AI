# Live Agentic RAG + MCP evaluation

Generated: 2026-07-23  
Mode: local showcase-ecommerce DataHub, read-only MCP, Qdrant index with 1,188 assets, `gpt-4.1-mini`.

## Protocol

Six independently executed requests covered catalog retrieval, schema lookup,
lineage lookup, impact routing, write/HITL routing, and a nonexistent-asset
safety case. No DataHub mutation was enabled or attempted. The four `orders`
dataset URNs used for retrieval ground truth were manually reviewed from the
local DataHub search result before the run.

## Results

| Category | Metric | Result | Interpretation |
|---|---|---:|---|
| Retrieval | Precision@6 | 0.667 | Four reviewed `orders` datasets appeared in six returned citations. |
| Retrieval | Recall@6 | 1.000 | All four reviewed relevant datasets were returned. |
| Retrieval | MRR@6 | 1.000 | First relevant dataset was ranked first. |
| Retrieval | NDCG@6 | 1.000 | Relevant reviewed datasets occupied the ideal ranking positions. |
| Retrieval | Result diversity@6 | 0.867 | Entity/platform pair diversity proxy; not a claim of MMR reranking. |
| Agents | Router accuracy | 1.000 | Normal, impact and write/HITL routing matched expected safe actions. |
| Agents | Tool-selection accuracy | 1.000 | Expected allowlisted MCP tools matched each reviewed scenario. |
| Agents | Verification accuracy | 1.000 | Verified scenarios passed; the no-proof scenario failed verification. |
| Safety | Unsupported-claim block rate | 1.000 | The nonexistent asset was safely blocked. |
| Evidence | Verified-citation coverage | 1.000 | Every expected verified answer had citations. |
| Performance | Mean latency | 23,087.6 ms | End-to-end, including local DataHub MCP process calls. |
| Performance | p50 / p95 latency | 19,480.9 / 41,104.8 ms | The negative repair path dominates the tail. |
| Cost | Tokens | 8,406 | Planning plus answer calls across the six retained runs. |
| Cost | Estimated OpenAI cost | $0.004661 | Text-token estimate for `gpt-4.1-mini`; excludes local DataHub/Qdrant compute. |

## Interpretation and limits

- MRR and NDCG currently use one manually reviewed retrieval query. They are
  valid for this narrow showcase check but are **not** statistically sufficient
  to claim general retrieval quality. Add 20+ independently labelled queries
  across Snowflake, PostgreSQL, S3, dbt, Looker, PowerBI and Tableau before
  submission.
- `result_diversity@6` is a transparent diversity proxy. The retriever does
  not yet apply a Maximal Marginal Relevance reranker, so this number must not
  be labelled “MMR quality”.
- The first no-proof run exposed that a Qdrant fallback could lead to an
  unrelated live lookup. The fallback was removed, schema/lineage calls now
  require a live MCP-confirmed asset, and the negative case was re-run.
- The cost is calculated from safe API usage fields using the published
  [`gpt-4.1-mini` text rates](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
  ($0.40/M input and $1.60/M output at run time).
  It is an estimate, not an account invoice.

## Reproduction

```powershell
Set-Location C:\Users\Mega Pc\Desktop\lineageguard-ai
python .\evals\runners\run_agentic_rag_evals.py
python .\evals\runners\run_live_agentic_evals.py --api-base-url http://localhost:8000
```

The live runner is read-only. It returns `null` retrieval metrics when a case
has no manually reviewed `relevant_urns`; this is intentional and avoids
inventing quality claims.
