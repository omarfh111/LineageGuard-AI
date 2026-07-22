# Agentic RAG + MCP fixture baseline

Mode: offline committed fixtures — **not a live benchmark or provider-quality claim**.

| Metric | Result |
|---|---:|
| case count | 5 |
| asset precision | 1.0 |
| asset recall | 1.0 |
| lineage precision | 1.0 |
| lineage recall | 1.0 |
| schema exact match | 1.0 |
| tool selection accuracy | 1.0 |
| citation coverage verified answers | 1.0 |
| unsupported claim rate before guard | 0.4 |
| post verification unsupported claim rate | 0.0 |
| verification block rate | 1.0 |
| latency p95 ms | 540 |
| latency mean ms | 438.0 |
| estimated cost usd | 0.0 |

The fixture includes positive schema/lineage cases and negative cases where no proof is returned. A verification block is expected for every negative case. To publish a live score, save a dated ground-truth file, pinned model/provider version, latency distribution, token/cost ledger, DataHub datapack version, and reviewer sign-off.
