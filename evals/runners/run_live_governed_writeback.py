"""Opt-in live analyze -> judge -> HITL -> write-back -> compensation proof.

This runner writes only a DataHub Analysis document. It never changes a dataset
schema. Mutation is impossible unless ``--execute`` is supplied explicitly.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_ASSET = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,"
    "b2fd91.order_entry_db.order_entry.orders,PROD)"
)
EXPECTED_AUDIT = [
    "WRITEBACK_PREPARED",
    "APPROVED",
    "WRITEBACK_PENDING",
    "WRITEBACK_COMPLETED",
    "ROLLBACK_PENDING",
    "ROLLBACK_COMPLETED",
]


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 180,
) -> dict[str, Any] | list[dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - explicit CLI URL
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {error.code}: {detail}") from error


def timed_post(base_url: str, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = request_json("POST", f"{base_url.rstrip('/')}{path}", payload)
    if not isinstance(result, dict):
        raise RuntimeError(f"{path} returned an invalid response")
    return result, round((time.perf_counter() - started) * 1000, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--asset-urn", default=DEFAULT_ASSET)
    parser.add_argument("--execute", action="store_true", help="authorize document create and compensation")
    parser.add_argument("--output", type=Path, help="optional JSON evidence summary")
    args = parser.parse_args()

    analysis, analysis_ms = timed_post(
        args.api_base_url,
        "/api/v1/workflows/analyze",
        {
            "asset_urn": args.asset_urn,
            "change_type": "RENAME_COLUMN",
            "column_name": "order_status",
            "new_value": "order_status_code",
            "reason": "Professional validation of governed analysis document lifecycle",
            "environment": "STAGING",
            "lineage_depth": 1,
        },
    )
    analysis_run_id = str(analysis["analysis_run_id"])
    judging, judge_ms = timed_post(
        args.api_base_url,
        "/api/v1/workflows/judge",
        {"analysis_run_id": analysis_run_id, "repair_cycles": 0},
    )
    stored = judging["judging"]
    result = stored["result"]
    aggregate = result.get("aggregate_decision") or {}
    openai_status = (result.get("openai_verdict") or {}).get("verdict")
    groq_status = (result.get("groq_verdict") or {}).get("verdict")
    double_pass = (
        bool((result.get("deterministic_validation") or {}).get("passed"))
        and openai_status == "PASS"
        and groq_status == "PASS"
        and aggregate.get("decision") == "FINALIZE_READ_ONLY"
    )
    if not double_pass:
        raise RuntimeError(
            "Write-back gate closed: deterministic validation and both independent judges must PASS"
        )

    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "asset_urn": args.asset_urn,
        "analysis_run_id": analysis_run_id,
        "judging_run_id": stored["run_id"],
        "deterministic_validation": True,
        "openai_verdict": openai_status,
        "groq_verdict": groq_status,
        "aggregate_decision": aggregate.get("decision"),
        "analysis_latency_ms": analysis_ms,
        "judge_latency_ms": judge_ms,
        "mutation_executed": False,
    }
    if not args.execute:
        print(json.dumps(summary, indent=2))
        return 0

    idempotency_key = f"professional-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12]}"
    prepared, prepare_ms = timed_post(
        args.api_base_url,
        "/api/v1/writebacks/prepare",
        {"run_id": stored["run_id"], "idempotency_key": idempotency_key},
    )
    proposal_run_id = str(prepared["run_id"])
    approved, approve_ms = timed_post(
        args.api_base_url,
        f"/api/v1/writebacks/{proposal_run_id}/approve",
        {
            "decision": "APPROVE_REPORT",
            "comment": "Explicit professional validation approval for a compensable analysis document only.",
            "idempotency_key": idempotency_key,
        },
    )
    if approved.get("status") != "COMPLETED":
        raise RuntimeError(f"Write-back did not complete: {approved.get('status')}")

    rollback_payload = {
        "decision": "APPROVE_ROLLBACK",
        "comment": "Explicit compensation approval after successful live verification.",
        "idempotency_key": idempotency_key,
    }
    rollback_error: Exception | None = None
    rolled_back: dict[str, Any] | None = None
    rollback_ms = 0.0
    for _ in range(2):
        try:
            rolled_back, rollback_ms = timed_post(
                args.api_base_url,
                f"/api/v1/writebacks/{proposal_run_id}/rollback",
                rollback_payload,
            )
            if rolled_back.get("status") == "ROLLED_BACK":
                rollback_error = None
                break
        except Exception as error:  # one bounded idempotent compensation retry
            rollback_error = error
    if rolled_back is None or rolled_back.get("status") != "ROLLED_BACK":
        raise RuntimeError(
            f"COMPENSATION FAILED for proposal {proposal_run_id}; manual reconciliation required: {rollback_error}"
        )

    audit = request_json(
        "GET", f"{args.api_base_url.rstrip('/')}/api/v1/writebacks/{proposal_run_id}/audit"
    )
    if not isinstance(audit, list):
        raise RuntimeError("Write-back audit response is invalid")
    audit_types = [str(item.get("event_type")) for item in audit]
    if audit_types != EXPECTED_AUDIT:
        raise RuntimeError(f"Unexpected audit sequence: {audit_types}")

    summary.update(
        {
            "mutation_executed": True,
            "proposal_run_id": proposal_run_id,
            "document_urn": approved.get("snapshot", {}).get("document_urn"),
            "writeback_status": approved.get("status"),
            "compensation_status": rolled_back.get("status"),
            "audit_sequence": audit_types,
            "prepare_latency_ms": prepare_ms,
            "writeback_latency_ms": approve_ms,
            "compensation_latency_ms": rollback_ms,
        }
    )
    rendered = json.dumps(summary, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
