# Evaluation assets

`datasets/lineageguard-eval-v1.json` contains 20 manually curated reference cases: five per supported change type. It covers complete/no lineage, missing metadata, multi-hop and cross-platform lineage, invalid assets/columns, prompt injection, provider timeout, judge disagreement, write-back failure, and destructive changes.

The dataset is intentionally offline: it records reference expectations and is safe for CI. It does not claim that mock-based results measure the quality of a live DataHub instance or paid LLM providers.

Run the contract/coverage report from the repository root:

```powershell
python .\evals\runners\run_deterministic_evals.py
```

The runner writes `evals/reports/final-evaluation.md`. Live DataHub and provider measurements are documented separately as a manual pre-submission procedure in that report.

The reproducible local results are recorded in [`reports/local-validation-2026-07-20.md`](reports/local-validation-2026-07-20.md). They distinguish verified local behaviour from metrics that need an explicit paid-provider or disposable-environment run.
