"""Measure fixture-grounded quality gates for Agentic RAG + DataHub MCP.

The runner is deliberately offline: it measures the committed reference
fixtures, not provider quality. A live benchmark must record its own date,
dataset version, model and cost before any score is advertised.
"""

from __future__ import annotations

import argparse
import json
from math import ceil, log2
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "agentic-rag-eval-v1.json"
REPORT = ROOT / "evals" / "reports" / "agentic-rag-baseline.md"


def _prf(expected: set[str], actual: set[str]) -> tuple[float, float, float]:
    if not expected and not actual:
        return 1.0, 1.0, 1.0
    true_positive = len(expected & actual)
    precision = true_positive / len(actual) if actual else 0.0
    recall = true_positive / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _ranking_metrics(expected: set[str], ranked: list[str], k: int = 6) -> tuple[float, float, float, float]:
    """Return precision@k, recall@k, MRR and binary NDCG@k for one query."""

    if not expected:
        return 0.0, 0.0, 0.0, 0.0
    top = ranked[:k]
    hits = [item for item in top if item in expected]
    precision = len(hits) / len(top) if top else 0.0
    recall = len(hits) / len(expected)
    first_rank = next((index + 1 for index, item in enumerate(top) if item in expected), None)
    reciprocal_rank = 1 / first_rank if first_rank else 0.0
    dcg = sum(1 / log2(index + 2) for index, item in enumerate(top) if item in expected)
    ideal = sum(1 / log2(index + 2) for index in range(min(len(expected), k)))
    return precision, recall, reciprocal_rank, dcg / ideal if ideal else 0.0


def evaluate() -> dict[str, float | int]:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload["cases"]
    if len(cases) < 5 or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Agentic RAG fixture set must contain unique IDs and at least five cases")

    asset_expected: set[str] = set()
    asset_actual: set[str] = set()
    lineage_expected: set[str] = set()
    lineage_actual: set[str] = set()
    schema_scores: list[float] = []
    tools_correct = 0
    all_claims = 0
    unsupported_claims = 0
    invalid_cases = 0
    blocked_invalid_cases = 0
    latencies: list[float] = []
    costs: list[float] = []
    retrieval_precisions: list[float] = []
    retrieval_recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []

    for case in cases:
        expected = case["expected"]
        observed = case["observed"]
        asset_expected.update(expected["assets"])
        asset_actual.update(observed["assets"])
        if expected["assets"]:
            precision_at_k, recall_at_k, reciprocal_rank, ndcg = _ranking_metrics(
                set(expected["assets"]), observed.get("ranked_assets", observed["assets"])
            )
            retrieval_precisions.append(precision_at_k)
            retrieval_recalls.append(recall_at_k)
            reciprocal_ranks.append(reciprocal_rank)
            ndcgs.append(ndcg)
        lineage_expected.update(expected["lineage_facts"])
        lineage_actual.update(observed["lineage_facts"])
        schema_scores.append(_prf(set(expected["schema_facts"]), set(observed["schema_facts"]))[2])
        tools_correct += set(expected["tools"]) == set(observed["tools"])
        claims = observed["claims"]
        all_claims += len(claims)
        unsupported_claims += sum(not claim["supported"] for claim in claims)
        requires_proof = bool(expected["schema_facts"] or expected["lineage_facts"] or "no-" in case["id"])
        if "no-" in case["id"]:
            invalid_cases += 1
            blocked_invalid_cases += not observed["verification_passed"]
        latencies.append(float(observed["latency_ms"]))
        costs.append(float(observed["estimated_cost_usd"]))

    asset_precision, asset_recall, _ = _prf(asset_expected, asset_actual)
    lineage_precision, lineage_recall, _ = _prf(lineage_expected, lineage_actual)
    supported_claims = all_claims - unsupported_claims
    unblocked_unsupported = sum(
        sum(not claim["supported"] for claim in case["observed"]["claims"])
        for case in cases
        if case["observed"]["verification_passed"]
    )
    ranked_latencies = sorted(latencies)
    p95 = ranked_latencies[min(len(ranked_latencies) - 1, ceil(len(ranked_latencies) * 0.95) - 1)]
    return {
        "case_count": len(cases),
        "asset_precision": round(asset_precision, 3),
        "asset_recall": round(asset_recall, 3),
        "precision_at_6": round(mean(retrieval_precisions), 3),
        "recall_at_6": round(mean(retrieval_recalls), 3),
        "mean_reciprocal_rank_at_6": round(mean(reciprocal_ranks), 3),
        "ndcg_at_6": round(mean(ndcgs), 3),
        "lineage_precision": round(lineage_precision, 3),
        "lineage_recall": round(lineage_recall, 3),
        "schema_exact_match": round(mean(schema_scores), 3),
        "tool_selection_accuracy": round(tools_correct / len(cases), 3),
        "citation_coverage_verified_answers": round(supported_claims / supported_claims, 3) if supported_claims else 0.0,
        "unsupported_claim_rate_before_guard": round(unsupported_claims / all_claims, 3) if all_claims else 0.0,
        "post_verification_unsupported_claim_rate": round(unblocked_unsupported / all_claims, 3) if all_claims else 0.0,
        "verification_block_rate": round(blocked_invalid_cases / invalid_cases, 3) if invalid_cases else 0.0,
        "latency_p95_ms": int(p95),
        "latency_mean_ms": round(mean(latencies), 1),
        "estimated_cost_usd": round(sum(costs), 4),
    }


def render(metrics: dict[str, float | int]) -> str:
    rows = "\n".join(
        f"| {key.replace('_', ' ')} | {value} |" for key, value in metrics.items()
    )
    return f"""# Agentic RAG + MCP fixture baseline

Mode: offline committed fixtures — **not a live benchmark or provider-quality claim**.

| Metric | Result |
|---|---:|
{rows}

The fixture includes positive schema/lineage cases and negative cases where no proof is returned. A verification block is expected for every negative case. `precision_at_6`, `recall_at_6`, MRR and NDCG are ranking metrics on fixture-labelled relevant assets. MMR is a reranking strategy rather than an accuracy metric; report its configured lambda and a separate diversity measure only after enabling an MMR retriever. To publish a live score, save a dated ground-truth file, pinned model/provider version, latency distribution, token/cost ledger, DataHub datapack version, and reviewer sign-off.
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true", help="write the tracked baseline report")
    args = parser.parse_args()
    metrics = evaluate()
    if args.write_report:
        REPORT.write_text(render(metrics), encoding="utf-8")
        print(f"Wrote {REPORT.relative_to(ROOT)}")
    else:
        print(json.dumps(metrics, indent=2, sort_keys=True))
