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
    impact_type: str = "POTENTIAL_SCHEMA_IMPACT"
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


class PlanStep(BaseModel):
    """One proposed migration action; it is never executed by LineageGuard."""

    order: int = Field(ge=1)
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    affected_asset_urns: list[str]


class RecommendedTest(BaseModel):
    name: str
    category: str
    purpose: str
    affected_asset_urns: list[str]


class BusinessRollbackPlan(BaseModel):
    """A proposed business rollback, explicitly not an executable operation."""

    trigger_conditions: list[str]
    preservation_steps: list[str]
    reversal_steps: list[str]
    dependency_restore_steps: list[str]
    post_rollback_tests: list[RecommendedTest]
    responsible_owner_urns: list[str]
    success_criteria: list[str]
    execution_status: str = "NOT_EXECUTED"


class RemediationPlan(BaseModel):
    """Deterministic migration guidance derived from an evidence-backed report."""

    source_asset_urn: str
    change_type: ChangeType
    migration_steps: list[PlanStep]
    backward_compatible: bool | None
    forward_compatible: bool | None
    deprecation_period: str | None
    recommended_tests: list[RecommendedTest]
    downstream_checks: list[str]
    owners_to_notify: list[str]
    deployment_conditions: list[str]
    stop_conditions: list[str]
    rollback_plan: BusinessRollbackPlan
    execution_status: str = "NOT_EXECUTED"


class JudgeProvider(StrEnum):
    OPENAI = "openai"
    GROQ = "groq"


class JudgeStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class JudgeScores(BaseModel):
    grounding: int = Field(ge=0, le=5)
    technical_correctness: int = Field(ge=0, le=5)
    completeness: int = Field(ge=0, le=5)
    safety: int = Field(ge=0, le=5)
    actionability: int = Field(ge=0, le=5)


class JudgeVerdict(BaseModel):
    """Structured result from one independent LLM judge."""

    judge_provider: JudgeProvider
    judge_model: str
    verdict: JudgeStatus
    scores: JudgeScores
    critical_errors: list[str]
    non_critical_issues: list[str]
    repair_instructions: list[str]
    audit_rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class DeterministicValidation(BaseModel):
    passed: bool
    errors: list[str]


class AggregateDecision(StrEnum):
    FINALIZE_READ_ONLY = "FINALIZE_READ_ONLY"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    BLOCKED = "BLOCKED"


class JudgeAggregation(BaseModel):
    decision: AggregateDecision
    human_review_required: bool
    rationale: str


class JudgingRequest(BaseModel):
    impact_report: ImpactReport
    remediation_plan: RemediationPlan
    repair_cycles: int = Field(default=0, ge=0, le=2)


class CritiqueSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CritiqueIssue(BaseModel):
    severity: CritiqueSeverity
    finding: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list)


class AdvisoryCritique(BaseModel):
    """Advisory review performed before the independent final judges."""

    provider: str
    model: str
    summary: str = Field(min_length=1, max_length=2000)
    issues: list[CritiqueIssue]
    recommended_revisions: list[str]
    confidence: float = Field(ge=0, le=1)


class CritiqueRequest(BaseModel):
    impact_report: ImpactReport
    remediation_plan: RemediationPlan


class JudgingResult(BaseModel):
    deterministic_validation: DeterministicValidation
    openai_verdict: JudgeVerdict | None
    groq_verdict: JudgeVerdict | None
    aggregate_decision: JudgeAggregation | None


class HumanDecision(StrEnum):
    APPROVE_REPORT = "APPROVE_REPORT"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"
    APPROVE_ROLLBACK = "APPROVE_ROLLBACK"


class WritebackStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    WRITEBACK_PENDING = "WRITEBACK_PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class WritebackProposal(BaseModel):
    run_id: str
    idempotency_key: str = Field(min_length=8, max_length=200)
    report_hash: str
    target_asset_urn: str
    document_title: str
    document_content: str
    allowed_mutations: list[str] = Field(default_factory=lambda: ["save_document"])
    snapshot: dict[str, Any]
    status: WritebackStatus = WritebackStatus.PENDING_APPROVAL


class ApprovalRequest(BaseModel):
    decision: HumanDecision
    comment: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=200)


class AuditEvent(BaseModel):
    run_id: str
    event_type: str
    timestamp: datetime
    detail: dict[str, Any]


class WritebackPreparationRequest(BaseModel):
    judging_request: JudgingRequest
    judging_result: JudgingResult
    idempotency_key: str = Field(min_length=8, max_length=200)


class StoredJudgingResult(BaseModel):
    run_id: str
    result: JudgingResult


class JudgingRunSummary(BaseModel):
    """Safe, compact history view; full requests remain server-owned."""

    run_id: str
    created_at: datetime
    decision: AggregateDecision | None
    openai_status: JudgeStatus | None
    groq_status: JudgeStatus | None
