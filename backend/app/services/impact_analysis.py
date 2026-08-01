"""Evidence-backed, deterministic schema impact analysis."""

from __future__ import annotations

import re
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
from app.services.metadata_investigator import (
    MetadataInvestigation,
    MetadataInvestigationError,
    MetadataInvestigator,
)


class AnalysisInputError(ValueError):
    """Raised when DataHub evidence cannot support the requested analysis."""


class ImpactAnalysisService:
    """Collect read-only MCP evidence and calculate a reproducible risk score."""

    def __init__(self, client: DataHubMcpClient) -> None:
        self._client = client

    async def analyze(
        self, request: ChangeRequest, investigation: MetadataInvestigation | None = None
    ) -> ImpactReport:
        investigator = MetadataInvestigator(self._client)
        try:
            schema = (
                investigation.schema
                if investigation is not None
                else await investigator.inspect_schema(request)
            )
        except MetadataInvestigationError as error:
            raise AnalysisInputError(str(error)) from error
        fields = schema.get("fields", [])
        if not isinstance(fields, list):
            raise AnalysisInputError("DataHub returned an invalid schema response")
        if not fields:
            raise AnalysisInputError("The selected asset was not found or has no schema")

        field_map = _schema_field_map(fields)
        field_names = {field[0] for field in field_map.values()}
        _validate_change_against_schema(request, field_map)

        try:
            lineage = (
                investigation.lineage
                if investigation is not None
                else await investigator.inspect_lineage(request)
            )
        except MetadataInvestigationError as error:
            raise AnalysisInputError(str(error)) from error
        retrieved_at = (
            investigation.retrieved_at
            if investigation is not None
            else datetime.now(UTC)
        )

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
                    "field_types": {
                        name: data_type
                        for name, data_type in sorted(field_map.values())
                        if data_type is not None
                    },
                    "total_fields": schema.get("totalFields", len(fields)),
                },
                retrieved_at=retrieved_at,
            )
        ]
        impacts: list[ImpactItem] = []
        seen_urns: set[str] = set()
        lineage_rows: list[tuple[int, dict[str, Any], str, int]] = []

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

            degree = result.get("degree")
            normalized_degree = degree if isinstance(degree, int) and degree > 0 else 1
            lineage_rows.append((index, entity, asset_urn, normalized_degree))

        multi_hop_targets = [
            (request.asset_urn, asset_urn)
            for _, _, asset_urn, degree in lineage_rows
            if degree > 1
        ]
        verified_paths: dict[str, list[str]] = {}
        if multi_hop_targets:
            path_reader = getattr(self._client, "get_lineage_paths_many", None)
            if not callable(path_reader):
                raise AnalysisInputError(
                    "Multi-hop lineage requires get_lineage_paths_between evidence"
                )
            raw_paths = await path_reader(multi_hop_targets)
            if len(raw_paths) != len(multi_hop_targets):
                raise AnalysisInputError("DataHub returned an incomplete multi-hop path batch")
            for (_, target_urn), path_result in zip(
                multi_hop_targets, raw_paths, strict=True
            ):
                expected_degree = next(
                    degree
                    for _, _, asset_urn, degree in lineage_rows
                    if asset_urn == target_urn
                )
                path = _verified_lineage_path(
                    path_result, request.asset_urn, target_urn, expected_degree
                )
                if path is None:
                    raise AnalysisInputError(
                        f"No exact MCP lineage path was verified for {target_urn}"
                    )
                verified_paths[target_urn] = path

        for index, entity, asset_urn, degree in lineage_rows:
            lineage_path = (
                [request.asset_urn, asset_urn]
                if degree == 1
                else verified_paths[asset_urn]
            )

            evidence_id = f"ev_lineage_{index:03d}"
            owner_urns = _owner_urns(entity)
            platform_urn = _platform_urn(entity)
            criticality = _criticality(entity)
            evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    tool=(
                        "get_lineage_paths_between"
                        if degree > 1
                        else "get_lineage"
                    ),
                    asset_urn=asset_urn,
                    claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                    raw_reference={
                        "source_asset_urn": request.asset_urn,
                        "downstream_asset_urn": asset_urn,
                        "degree": degree,
                        "lineage_path": lineage_path,
                        "owner_urns": owner_urns,
                        "platform_urn": platform_urn,
                        "criticality": criticality.value,
                    },
                    retrieved_at=retrieved_at,
                )
            )
            impacts.append(
                ImpactItem(
                    asset_urn=asset_urn,
                    asset_type=str(entity.get("type", "UNKNOWN")),
                    lineage_path=lineage_path,
                    owner_urns=owner_urns,
                    platform_urn=platform_urn,
                    criticality=criticality,
                    evidence_ids=[evidence_id],
                )
            )

        total_downstreams = downstream.get("total") if isinstance(downstream, dict) else None
        observed_total = (
            total_downstreams
            if isinstance(total_downstreams, int) and total_downstreams >= len(impacts)
            else len(impacts)
        )
        evidence.insert(
            1,
            EvidenceItem(
                evidence_id="ev_lineage_summary",
                tool="get_lineage",
                asset_urn=request.asset_urn,
                claim_type=ClaimType.DOWNSTREAM_DEPENDENCY,
                raw_reference={
                    "source_asset_urn": request.asset_urn,
                    "returned_assets": len(impacts),
                    "total_downstreams": observed_total,
                    "direction": "DOWNSTREAM",
                    "max_hops": request.lineage_depth,
                },
                retrieved_at=retrieved_at,
            ),
        )

        missing_metadata = expected_missing_metadata(
            impacts, total_downstreams=observed_total
        )
        risk_assessment = calculate_risk_assessment(
            request, impacts, missing_metadata
        )
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


def _schema_field_map(fields: list[Any]) -> dict[str, tuple[str, str | None]]:
    """Return case-insensitive field identities while preserving DataHub spelling."""

    field_map: dict[str, tuple[str, str | None]] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        raw_name = field.get("fieldPath") or field.get("field_path") or field.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        name = raw_name.strip()
        raw_type = (
            field.get("nativeDataType")
            or field.get("native_data_type")
            or field.get("type")
        )
        data_type = raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else None
        key = name.casefold()
        if key in field_map and field_map[key][0] != name:
            raise AnalysisInputError(
                f"Schema contains case-colliding fields {field_map[key][0]!r} and {name!r}"
            )
        field_map[key] = (name, data_type)
    return field_map


def _normalize_data_type(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _validate_change_against_schema(
    request: ChangeRequest, field_map: dict[str, tuple[str, str | None]]
) -> None:
    source_key = (request.column_name or "").casefold()
    if request.change_type is ChangeType.ADD_COLUMN:
        if source_key in field_map:
            raise AnalysisInputError(
                f"Column {request.column_name!r} already exists; ADD_COLUMN would be a duplicate"
            )
        return
    if source_key not in field_map:
        raise AnalysisInputError(
            f"Column {request.column_name!r} does not exist in the retrieved schema"
        )
    if request.change_type is ChangeType.RENAME_COLUMN:
        target_key = (request.new_value or "").casefold()
        if target_key in field_map:
            raise AnalysisInputError(
                f"Rename target {request.new_value!r} already exists in the retrieved schema"
            )
    if request.change_type is ChangeType.CHANGE_COLUMN_TYPE:
        current_type = field_map[source_key][1]
        if current_type is None:
            raise AnalysisInputError(
                f"Current type for {request.column_name!r} is missing from DataHub schema evidence"
            )
        if _normalize_data_type(current_type) == _normalize_data_type(request.new_value or ""):
            raise AnalysisInputError(
                f"Column {request.column_name!r} already has type {current_type!r}"
            )


def _verified_lineage_path(
    result: dict[str, Any], source_urn: str, target_urn: str, expected_degree: int
) -> list[str] | None:
    """Select the shortest exact, simple dataset path returned by DataHub MCP."""

    content = result.get("structuredContent", {}) if isinstance(result, dict) else {}
    if not isinstance(content, dict):
        return None
    paths = content.get("paths", [])
    if not isinstance(paths, list):
        return None
    candidates: list[list[str]] = []
    for path_object in paths:
        entities = path_object.get("path", []) if isinstance(path_object, dict) else []
        if not isinstance(entities, list):
            continue
        urns: list[str] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            urn = entity.get("urn")
            entity_type = str(entity.get("type", "")).upper()
            if not isinstance(urn, str) or not urn.startswith("urn:li:"):
                continue
            if entity_type == "QUERY" or urn.startswith("urn:li:query:"):
                continue
            urns.append(urn)
        if (
            len(urns) == expected_degree + 1
            and urns[0] == source_urn
            and urns[-1] == target_urn
            and len(urns) == len(set(urns))
        ):
            candidates.append(urns)
    return min(candidates, key=lambda path: (len(path), path)) if candidates else None


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


def expected_missing_metadata(
    impacts: list[ImpactItem], *, total_downstreams: int
) -> list[str]:
    """Reconstruct the only metadata-uncertainty facts accepted by Gate 0."""

    missing: list[str] = []
    for impact in impacts:
        if not impact.owner_urns:
            missing.append(f"{impact.asset_urn}: owners missing")
        if not impact.platform_urn:
            missing.append(f"{impact.asset_urn}: platform missing")
    if total_downstreams > len(impacts):
        missing.append(
            "Lineage response is truncated: "
            f"{len(impacts)} of {total_downstreams} downstream assets were returned"
        )
    return missing


def calculate_risk_assessment(
    request: ChangeRequest,
    impacts: list[ImpactItem],
    missing_metadata: list[str],
) -> RiskAssessment:
    """Calculate risk only from normalized request and observed report facts."""

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
