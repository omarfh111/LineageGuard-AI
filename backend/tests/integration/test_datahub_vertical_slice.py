"""Opt-in verification against the running LineageGuard and DataHub services."""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_DATAHUB_INTEGRATION") != "1",
    reason="Set RUN_DATAHUB_INTEGRATION=1 after starting local containers.",
)
def test_showcase_asset_search_schema_and_lineage() -> None:
    """Retrieve a real showcase dataset and its schema and dependencies."""

    base_url = os.getenv("LINEAGEGUARD_API_URL", "http://localhost:8000")
    with httpx.Client(base_url=base_url, timeout=90.0) as client:
        search = client.get("/api/v1/datahub/search", params={"query": "orders"})
        assert search.status_code == 200, search.text
        results = search.json()["result"]["structuredContent"]["searchResults"]
        asset_urn = next(
            item["entity"]["urn"]
            for item in results
            if item["entity"]["urn"].startswith("urn:li:dataset:")
        )

        schema = client.get("/api/v1/datahub/schema", params={"asset_urn": asset_urn})
        assert schema.status_code == 200, schema.text
        assert schema.json()["result"]["structuredContent"]["totalFields"] > 0

        lineage = client.get(
            "/api/v1/datahub/lineage",
            params={
                "asset_urn": asset_urn,
                "direction": "DOWNSTREAM",
                "max_hops": 3,
            },
        )
        assert lineage.status_code == 200, lineage.text
        assert lineage.json()["result"]["structuredContent"]["downstreams"]["total"] > 0
