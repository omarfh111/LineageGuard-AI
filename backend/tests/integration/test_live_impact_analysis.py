"""Opt-in end-to-end proof check for the deterministic impact report."""

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
def test_live_impact_report_has_evidence_for_every_asset() -> None:
    base_url = os.getenv("LINEAGEGUARD_API_URL", "http://localhost:8000")
    sample_path = Path(__file__).parents[3] / "examples" / "drop-column-orders.json"

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        response = client.post(
            "/api/v1/analyses/impact",
            content=sample_path.read_bytes(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200, response.text
    report = response.json()
    evidence_ids = {item["evidence_id"] for item in report["evidence_bundle"]["items"]}
    assert report["blast_radius"] > 0
    assert all(
        impact["evidence_ids"]
        and set(impact["evidence_ids"]).issubset(evidence_ids)
        for impact in report["impacted_assets"]
    )
