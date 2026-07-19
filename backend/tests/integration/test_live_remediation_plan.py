"""Opt-in end-to-end check that remediation remains guidance only."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_DATAHUB_INTEGRATION") != "1",
    reason="Set RUN_DATAHUB_INTEGRATION=1 after starting local containers.",
)
def test_live_remediation_plan_never_executes_a_change() -> None:
    base_url = os.getenv("LINEAGEGUARD_API_URL", "http://localhost:8000")
    sample_path = Path(__file__).parents[3] / "examples" / "drop-column-orders.json"

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        report_response = client.post(
            "/api/v1/analyses/impact",
            content=sample_path.read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert report_response.status_code == 200, report_response.text
        plan_response = client.post(
            "/api/v1/remediations/plan",
            json=report_response.json(),
        )

    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["execution_status"] == "NOT_EXECUTED"
    assert plan["rollback_plan"]["execution_status"] == "NOT_EXECUTED"
