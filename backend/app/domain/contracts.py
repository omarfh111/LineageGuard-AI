"""Phase 2 contracts for read-only schema impact analysis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChangeType(StrEnum):
    """Schema changes supported by the MVP."""

    ADD_COLUMN = "ADD_COLUMN"
    RENAME_COLUMN = "RENAME_COLUMN"
    CHANGE_COLUMN_TYPE = "CHANGE_COLUMN_TYPE"
    DROP_COLUMN = "DROP_COLUMN"


class Environment(StrEnum):
    """Execution environments accepted by the request contract."""

    DEMO = "DEMO"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class Criticality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ClaimType(StrEnum):
    ASSET_EXISTS = "ASSET_EXISTS"
    SCHEMA_FIELD = "SCHEMA_FIELD"
    DOWNSTREAM_DEPENDENCY = "DOWNSTREAM_DEPENDENCY"


class ChangeRequest(BaseModel):
    """A normalized, non-mutating request to assess a schema change."""

    asset_urn: str = Field(min_length=1, pattern=r"^urn:li:")
    change_type: ChangeType
    column_name: str | None = Field(default=None, min_length=1)
    new_value: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=5, max_length=1000)
    environment: Environment
    lineage_depth: int = Field(default=3, ge=1, le=5)
    column_nullable: bool | None = None
    type_change_compatible: bool | None = None

    @model_validator(mode="after")
    def validate_change_details(self) -> "ChangeRequest":
        if self.change_type is not ChangeType.ADD_COLUMN and not self.column_name:
            raise ValueError("column_name is required for this change type")
        if self.change_type in {
            ChangeType.RENAME_COLUMN,
            ChangeType.CHANGE_COLUMN_TYPE,
        } and not self.new_value:
            raise ValueError("new_value is required for rename and type changes")
        return self


class EvidenceItem(BaseModel):
    """An immutable reference to metadata retrieved through DataHub MCP."""

    evidence_id: str
    source: str = "datahub_mcp"
    tool: str
    asset_urn: str
    claim_type: ClaimType
    raw_reference: dict[str, Any]
    retrieved_at: datetime


class EvidenceBundle(BaseModel):
    """Versioned collection of evidence backing a single analysis."""

    source_asset_urn: str
    items: list[EvidenceItem]


class ImpactItem(BaseModel):
    """A downstream asset with explicit DataHub evidence."""

    asset_urn: str
    asset_type: str
    impact_type: str = "SCHEMA_BREAK"
    lineage_path: list[str]
    owner_urns: list[str]
    platform_urn: str | None = None
    criticality: Criticality
    evidence_ids: list[str] = Field(min_length=1)


class RiskComponents(BaseModel):
    change_severity: int = Field(ge=0, le=100)
    blast_radius: int = Field(ge=0, le=100)
    asset_criticality: int = Field(ge=0, le=100)
    cross_platform_impact: int = Field(ge=0, le=100)
    metadata_uncertainty: int = Field(ge=0, le=100)


class RiskAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    level: RiskLevel
    components: RiskComponents
    explanation: list[str]


class ImpactReport(BaseModel):
    """Structured Phase 2 analysis with no recommendations or mutations."""

    request: ChangeRequest
    evidence_bundle: EvidenceBundle
    blast_radius: int = Field(ge=0)
    impacted_assets: list[ImpactItem]
    missing_metadata: list[str]
    risk_assessment: RiskAssessment
    confidence: float = Field(ge=0, le=1)
