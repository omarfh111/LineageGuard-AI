# Evaluation assets

`datasets/lineageguard-eval-v1.json` contains 20 manually curated reference cases: five per supported change type. It covers complete/no lineage, missing metadata, multi-hop and cross-platform lineage, invalid assets/columns, prompt injection, provider timeout, judge disagreement, write-back failure, and destructive changes.

The dataset is intentionally offline: it records reference expectations and is safe for CI. It does not claim that mock-based results measure the quality of a live DataHub instance or paid LLM providers.

Run the contract/coverage report from the repository root:

```powershell
python .\evals\runners\run_deterministic_evals.py
```

The runner writes `evals/reports/final-evaluation.md`. Live DataHub and provider measurements are documented separately as a manual pre-submission procedure in that report.

The reproducible local results are recorded in [`reports/local-validation-2026-07-20.md`](reports/local-validation-2026-07-20.md). They distinguish verified local behaviour from metrics that need an explicit paid-provider or disposable-environment run.

## Agentic RAG metrics

`runners/run_agentic_rag_evals.py` is the no-cost fixture regression suite. It
reports precision@6, recall@6, MRR@6, NDCG@6, schema exact match, tool routing,
evidence coverage, unsupported-claim blocking, latency and fixture cost.

`runners/run_live_agentic_evals.py` runs a bounded read-only benchmark against
the running LineageGuard API. It records actual token usage and a model-rate
cost estimate returned by the API, plus p50/p95 latency, router accuracy,
tool-selection accuracy, verification accuracy and safety block rate. Add
`relevant_urns` to a case only after manual DataHub ground-truth review.

The live runner also reports three claim-level guard metrics from the public
verification contract:

- `claim_support_coverage`: supported factual claims / extracted factual claims;
- `unsupported_claim_escape_rate`: unsupported claims in responses marked verified / all factual claims (target: `0`);
- `fully_supported_verified_answer_rate`: expected verified cases whose every factual claim is supported.

These are deterministic evidence-binding measurements, not semantic-quality
scores from another LLM. Human review is still required to judge whether the
authoritative MCP source itself is complete and whether answer wording is useful.

The evaluated local showcase result is in
[`reports/live-agentic-rag-2026-07-23.md`](reports/live-agentic-rag-2026-07-23.md).
