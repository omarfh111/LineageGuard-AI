"""Read-only DataHub metadata-investigator agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import ChangeRequest


class MetadataInvestigationError(ValueError):
    """Raised when DataHub cannot provide usable evidence for the request."""


@dataclass(frozen=True)
class MetadataInvestigation:
    """Server-side evidence collected once and consumed by impact analysis."""

    schema: dict[str, Any]
    lineage: dict[str, Any]
    retrieved_at: datetime


class MetadataInvestigator:
    """Collect the schema and downstream lineage through allowlisted MCP tools."""

    def __init__(self, client: DataHubMcpClient) -> None:
        self._client = client

    async def investigate(self, request: ChangeRequest) -> MetadataInvestigation:
        schema_result = await self._client.list_schema_fields(request.asset_urn)
        schema = _structured_content(schema_result)
        fields = schema.get("fields", [])
        if not isinstance(fields, list):
            raise MetadataInvestigationError("DataHub returned an invalid schema response")
        if not fields:
            raise MetadataInvestigationError("The selected asset was not found or has no schema")

        lineage_result = await self._client.get_lineage(
            request.asset_urn, "DOWNSTREAM", request.lineage_depth
        )
        lineage = _structured_content(lineage_result)
        downstream = lineage.get("downstreams", {})
        if not isinstance(downstream, dict) or not isinstance(
            downstream.get("searchResults", []), list
        ):
            raise MetadataInvestigationError("DataHub returned an invalid lineage response")

        return MetadataInvestigation(schema=schema, lineage=lineage, retrieved_at=datetime.now(UTC))


def _structured_content(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("structuredContent", {})
    return content if isinstance(content, dict) else {}
