"""Run a bounded, reproducible live Agentic RAG + MCP benchmark.

The script calls only LineageGuard's read-only chat endpoint. It deliberately
does not call write-back, mutate DataHub, or read API keys. Provider usage is
reported only when the API returns safe token telemetry.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from math import log2
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "evals" / "datasets" / "live-agentic-rag-template.json"


def percentile(values: list[float], point: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    index = min(len(ranked) - 1, max(0, round((len(ranked) - 1) * point)))
    return ranked[index]


def ranking(expected: set[str], actual: list[str], k: int) -> tuple[float, float, float, float]:
    if not expected:
        return 0.0, 0.0, 0.0, 0.0
    top = actual[:k]
    hits = [urn for urn in top if urn in expected]
    precision = len(hits) / len(top) if top else 0.0
    recall = len(hits) / len(expected)
    rank = next((position + 1 for position, urn in enumerate(top) if urn in expected), None)
    mrr = 1 / rank if rank else 0.0
    dcg = sum(1 / log2(position + 2) for position, urn in enumerate(top) if urn in expected)
    ideal = sum(1 / log2(position + 2) for position in range(min(len(expected), k)))
    return precision, recall, mrr, dcg / ideal if ideal else 0.0


def result_diversity(citations: list[dict[str, Any]], k: int) -> float:
    """A transparent diversity proxy; this is not MMR reranking quality."""

    top = citations[:k]
    if len(top) < 2:
        return 1.0 if top else 0.0
    pairs = 0
    distinct = 0
    for index, left in enumerate(top):
        left_key = (left.get("entity_type"), left.get("platform_urn"))
        for right in top[index + 1 :]:
            pairs += 1
            distinct += left_key != (right.get("entity_type"), right.get("platform_urn"))
    return distinct / pairs if pairs else 0.0


def post_json(url: str, body: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - explicit local URL from CLI
        return json.loads(response.read().decode("utf-8"))


def run(api_base_url: str, cases_path: Path, timeout_seconds: float, k: int) -> dict[str, Any]:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload["cases"]
    outcomes: list[dict[str, Any]] = []
    latencies: list[float] = []
    costs: list[float] = []
    tokens: list[int] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    diversities: list[float] = []
    router_correct = 0
    verifier_correct = 0
    tool_correct = 0
    cited_verified = 0
    expected_verified_cases = 0
    negative_cases = 0
    safely_blocked_cases = 0

    for case in cases:
        started = time.perf_counter()
        try:
            response = post_json(
                f"{api_base_url.rstrip('/')}/api/v1/chat/query",
                {"message": case["message"], "memory_enabled": False, "max_sources": k},
                timeout_seconds,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            citations = response.get("citations", [])
            urns = [citation.get("urn") for citation in citations if isinstance(citation.get("urn"), str)]
            expected = case.get("expected", {})
            expected_urns = set(expected.get("relevant_urns", []))
            if expected_urns:
                precision, recall, mrr, ndcg = ranking(expected_urns, urns, k)
                precisions.append(precision); recalls.append(recall); mrrs.append(mrr); ndcgs.append(ndcg)
            trace = response.get("agent_trace", [])
            tool_trace = " ".join(
                str(step.get("detail", "")) for step in trace if step.get("id") == "mcp_tools"
            )
            expected_tools = set(expected.get("tools", []))
            observed_tools = {tool for tool in ("search", "list_schema_fields", "get_lineage") if tool in tool_trace}
            tool_ok = not expected_tools or observed_tools == expected_tools
            action = (response.get("action_proposal") or {}).get("action")
            route_ok = action == expected.get("action", action)
            actual_verification = (response.get("verification") or {}).get("passed")
            expected_verification = expected.get("verification_passed", True)
            verification_ok = actual_verification == expected_verification
            usage = response.get("model_usage") or {}
            if isinstance(usage.get("total_tokens"), int): tokens.append(usage["total_tokens"])
            if isinstance(usage.get("estimated_cost_usd"), (int, float)): costs.append(float(usage["estimated_cost_usd"]))
            diversities.append(result_diversity(citations, k))
            if expected_verification:
                expected_verified_cases += 1
                cited_verified += int(bool(citations) and actual_verification is True)
            else:
                negative_cases += 1
                safely_blocked_cases += int(actual_verification is False)
            router_correct += int(route_ok); verifier_correct += int(verification_ok); tool_correct += int(tool_ok)
            outcomes.append({"id": case["id"], "status": "ok", "latency_ms": round(latency_ms, 1), "route_ok": route_ok, "tools_ok": tool_ok, "verification_ok": verification_ok, "citation_count": len(citations), "model_usage": usage})
            latencies.append(latency_ms)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            latencies.append((time.perf_counter() - started) * 1000)
            outcomes.append({"id": case["id"], "status": "error", "error": type(error).__name__})

    total = len(cases)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "live_read_only_agentic_rag",
        "case_file": str(cases_path.relative_to(ROOT)),
        "case_count": total,
        "completed_cases": sum(item["status"] == "ok" for item in outcomes),
        "retrieval_ground_truth_cases": len(precisions),
        "precision_at_k": round(mean(precisions), 3) if precisions else None,
        "recall_at_k": round(mean(recalls), 3) if recalls else None,
        "mrr_at_k": round(mean(mrrs), 3) if mrrs else None,
        "ndcg_at_k": round(mean(ndcgs), 3) if ndcgs else None,
        "result_diversity_at_k": round(mean(diversities), 3) if diversities else None,
        "router_accuracy": round(router_correct / total, 3) if total else 0.0,
        "tool_selection_accuracy": round(tool_correct / total, 3) if total else 0.0,
        "verification_accuracy": round(verifier_correct / total, 3) if total else 0.0,
        "verified_citation_coverage": round(cited_verified / expected_verified_cases, 3) if expected_verified_cases else None,
        "unsupported_claim_block_rate": round(safely_blocked_cases / negative_cases, 3) if negative_cases else None,
        "latency_mean_ms": round(mean(latencies), 1) if latencies else 0.0,
        "latency_p50_ms": round(median(latencies), 1) if latencies else 0.0,
        "latency_p95_ms": round(percentile(latencies, 0.95), 1) if latencies else 0.0,
        "total_tokens": sum(tokens),
        "estimated_cost_usd": round(sum(costs), 8) if costs else None,
        "outcomes": outcomes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--case-id", action="append", help="run only one or more named cases")
    parser.add_argument("--output", type=Path, help="optional untracked JSON result path")
    args = parser.parse_args()
    if args.case_id:
        source = json.loads(args.cases.read_text(encoding="utf-8"))
        selected = [case for case in source["cases"] if case["id"] in set(args.case_id)]
        if len(selected) != len(set(args.case_id)):
            raise SystemExit("One or more --case-id values do not exist in the case file")
        temporary_cases = ROOT / "evals" / "datasets" / ".live-agentic-rag-selected.json"
        # The selected manifest is intentionally ephemeral; it is never a report.
        temporary_cases.write_text(json.dumps({**source, "cases": selected}), encoding="utf-8")
        try:
            result = run(args.api_base_url, temporary_cases, args.timeout_seconds, args.k)
        finally:
            temporary_cases.unlink(missing_ok=True)
    else:
        result = run(args.api_base_url, args.cases, args.timeout_seconds, args.k)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
