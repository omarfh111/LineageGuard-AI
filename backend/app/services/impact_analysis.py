"""Evidence-backed, deterministic schema impact analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import (
    ChangeRequest,
    ChangeType,
    ClaimType,
    Criticality,
    EvidenceBundle,
    EvidenceItem,
    ImpactItem,
    ImpactReport,
    RiskAssessment,
    RiskComponents,
    RiskLevel,
)


class AnalysisInputError(ValueError):
    """Raised when DataHub evidence cannot support the requested analysis."""


class ImpactAnalysisService:
    """Collect read-only MCP evidence and calculate a reproducible risk score."""

    def __init__(self, client: DataHubMcpClient) -> None:
        self._client = client

    async def analyze(self, request: ChangeRequest) -> ImpactReport:
        retrieved_at = datetime.now(UTC)
        schema_result = await self._client.list_schema_fields(request.asset_urn)
        schema = _structured_content(schema_result)
        fields = schema.get("fields", [])
        if not isinstance(fields, list):
            raise AnalysisInputError("DataHub returned an invalid schema response")
        if not fields:
            raise AnalysisInputError("The selected asset was not found or has no schema")

        field_names = {field.get("fieldPath") for field in fields if isinstance(field, dict)}
        if (
            request.change_type is not ChangeType.ADD_COLUMN
            and request.column_name not in field_names
        ):
            raise AnalysisInputError(
                f"Column {request.column_name!r} does not exist in the retrieved schema"
            )

        lineage_result = await self._client.get_lineage(
            request.asset_urn, "DOWNSTREAM", request.lineage_depth
        )
        lineage = _structured_content(lineage_result)
        downstream = lineage.get("downstreams", {})
        search_results = downstream.get("searchResults", []) if isinstance(downstream, dict) else []
        if not isinstance(search_results, list):
            raise AnalysisInputError("DataHub returned an invalid lineage response")

        evidence = [
            EvidenceItem(
                evidence_id="ev_schema_source",
                tool="list_schema_fields",
                asset_urn=request.asset_urn,
                claim_type=ClaimType.SCHEMA_FIELD,
                raw_reference={
                    "field_names": sorted(name for name in field_names if name),
                    "total_fields": schema.get("totalFields", len(fields)),
                },
                retrieved_at=retrieved_at,
            )
        ]
        impacts: list[ImpactItem] = []
        missing_metadata: list[str] = []
        seen_urns: set[str] = set()

        for index, result in enumerate(search_results, start=1):
            if not isinstance(result, dict) or not isinstance(result.get("entity"), dict):
                continue
            entity = result["entity"]
            asset_urn = entity.get("urn")
            if not isinstance(asset_urn, str) or not asset_urn.startswith("urn:li:"):
                continue
            if asset_urn in seen_urns:
                continue
            seen_urns.add(asset_urn)

            evidence_id = f"ev_lineage_{index:03d}"
            owner_urns = _owner_urns(entity)
            platform_urn = _platform_urn(entity)
            if not owner_urns:
                missing_metadata.append(f"{asset_urn}: owners missing")
            if not platform_urn:
                missing_metadata.append(f"{asset_urn}: platform missing")
            evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    tool="get_lineage",
                    asset_urn=asset_urn,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={
                        "source_asset_urn": request.asset_urn,
                        "downstream_asset_urn": asset_urn,
                        "degree": result.get("degree"),
                    },
                    retrieved_at=retrieved_at,
                )
            )
            impacts.append(
                ImpactItem(
                    asset_urn=asset_urn,
                    asset_type=str(entity.get("type", "UNKNOWN")),
                    lineage_path=[request.asset_urn, asset_urn],
                    owner_urns=owner_urns,
                    platform_urn=platform_urn,
                    criticality=_criticality(entity),
                    evidence_ids=[evidence_id],
                )
            )

        total_downstreams = downstream.get("total") if isinstance(downstream, dict) else None
        if isinstance(total_downstreams, int) and total_downstreams > len(impacts):
            missing_metadata.append(
                "Lineage response is truncated: "
                f"{len(impacts)} of {total_downstreams} downstream assets were returned"
            )

        risk_assessment = _calculate_risk(request, impacts, missing_metadata)
        confidence = round(max(0.0, 1 - risk_assessment.components.metadata_uncertainty / 100), 2)
        return ImpactReport(
            request=request,
            evidence_bundle=EvidenceBundle(
                source_asset_urn=request.asset_urn,
                items=evidence,
            ),
            blast_radius=len(impacts),
            impacted_assets=impacts,
            missing_metadata=missing_metadata,
            risk_assessment=risk_assessment,
            confidence=confidence,
        )


def _structured_content(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("structuredContent", {})
    return content if isinstance(content, dict) else {}


def _owner_urns(entity: dict[str, Any]) -> list[str]:
    ownership = entity.get("ownership", {})
    owners = ownership.get("owners", []) if isinstance(ownership, dict) else []
    return [
        owner["owner"]["urn"]
        for owner in owners
        if isinstance(owner, dict)
        and isinstance(owner.get("owner"), dict)
        and isinstance(owner["owner"].get("urn"), str)
    ]


def _platform_urn(entity: dict[str, Any]) -> str | None:
    platform = entity.get("platform", {})
    if isinstance(platform, dict) and isinstance(platform.get("urn"), str):
        return platform["urn"]
    return None


def _criticality(entity: dict[str, Any]) -> Criticality:
    tags = entity.get("tags", {})
    tag_names = " ".join(
        str(tag.get("tag", {}).get("properties", {}).get("name", "")).lower()
        for tag in tags.get("tags", [])
        if isinstance(tag, dict)
    ) if isinstance(tags, dict) else ""
    if "critical" in tag_names:
        return Criticality.CRITICAL
    if "gold" in tag_names or "authoritative" in tag_names:
        return Criticality.HIGH
    return Criticality.MEDIUM


def _calculate_risk(
    request: ChangeRequest,
    impacts: list[ImpactItem],
    missing_metadata: list[str],
) -> RiskAssessment:
    severity = _change_severity(request)
    blast_radius = min(100, len(impacts) * 10)
    criticality_scores = {
        Criticality.LOW: 25,
        Criticality.MEDIUM: 50,
        Criticality.HIGH: 75,
        Criticality.CRITICAL: 100,
    }
    asset_criticality = max(
        (criticality_scores[item.criticality] for item in impacts), default=50
    )
    platforms = {item.platform_urn for item in impacts if item.platform_urn}
    cross_platform = min(100, max(0, len(platforms) - 1) * 25)
    uncertainty = min(100, round(100 * len(missing_metadata) / max(1, len(impacts))))
    components = RiskComponents(
        change_severity=severity,
        blast_radius=blast_radius,
        asset_criticality=asset_criticality,
        cross_platform_impact=cross_platform,
        metadata_uncertainty=uncertainty,
    )
    score = round(
        0.30 * severity
        + 0.30 * blast_radius
        + 0.20 * asset_criticality
        + 0.10 * cross_platform
        + 0.10 * uncertainty
    )
    level = (
        RiskLevel.LOW if score <= 29 else RiskLevel.MEDIUM if score <= 59
        else RiskLevel.HIGH if score <= 79 else RiskLevel.CRITICAL
    )
    return RiskAssessment(
        score=score,
        level=level,
        components=components,
        explanation=[
            f"Change severity is {severity}/100 for {request.change_type}.",
            f"Blast radius is {len(impacts)} downstream assets ({blast_radius}/100).",
            f"{len(platforms)} downstream platform(s) were observed ({cross_platform}/100).",
            f"Metadata uncertainty is {uncertainty}/100 from missing owners or platforms.",
            "Weighted score = 30% change severity + 30% blast radius + 20% asset criticality + 10% cross-platform impact + 10% metadata uncertainty.",
        ],
    )


def _change_severity(request: ChangeRequest) -> int:
    if request.change_type is ChangeType.ADD_COLUMN:
        return 10 if request.column_nullable is not False else 35
    if request.change_type is ChangeType.RENAME_COLUMN:
        return 60
    if request.change_type is ChangeType.CHANGE_COLUMN_TYPE:
        return 75 if request.type_change_compatible is False else 50
    return 90
