"""Phase 2 contracts for read-only schema impact analysis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("column_name", "new_value", mode="before")
    @classmethod
    def normalize_change_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_change_details(self) -> "ChangeRequest":
        if not self.column_name:
            raise ValueError("column_name is required for every schema change")
        if self.change_type in {
            ChangeType.RENAME_COLUMN,
            ChangeType.CHANGE_COLUMN_TYPE,
        } and not self.new_value:
            raise ValueError("new_value is required for rename and type changes")
        if (
            self.change_type is ChangeType.RENAME_COLUMN
            and self.new_value
            and self.column_name.casefold() == self.new_value.casefold()
        ):
            raise ValueError("A rename target must differ from the current column name")
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


class StoredAnalysisJudgingRequest(BaseModel):
    """Reference a server-owned analysis instead of accepting a browser copy."""

    analysis_run_id: str = Field(min_length=8, max_length=100)
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
    WRITEBACK_UNCERTAIN = "WRITEBACK_UNCERTAIN"
    COMPLETED = "COMPLETED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLBACK_UNCERTAIN = "ROLLBACK_UNCERTAIN"
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


class WritebackProposalView(BaseModel):
    """Public proposal projection that never exposes the approval key."""

    run_id: str
    report_hash: str
    target_asset_urn: str
    document_title: str
    document_content: str
    allowed_mutations: list[str]
    snapshot: dict[str, Any]
    status: WritebackStatus

    @classmethod
    def from_proposal(cls, proposal: WritebackProposal) -> "WritebackProposalView":
        return cls.model_validate(
            proposal.model_dump(exclude={"idempotency_key"})
        )


class ApprovalRequest(BaseModel):
    decision: HumanDecision
    comment: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=200)


class WritebackReconciliationAction(StrEnum):
    ADOPT_COMPLETED_DOCUMENT = "ADOPT_COMPLETED_DOCUMENT"
    CONFIRM_NO_DOCUMENT_CREATED = "CONFIRM_NO_DOCUMENT_CREATED"


class WritebackReconciliationRequest(BaseModel):
    action: WritebackReconciliationAction
    comment: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=200)
    document_urn: str | None = None


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


class WorkflowNodeStatus(StrEnum):
    """Visible state of one non-mutating workflow node."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    AWAITING_HUMAN = "AWAITING_HUMAN"


class WorkflowNode(BaseModel):
    id: str
    label: str
    kind: str
    status: WorkflowNodeStatus
    description: str


class WorkflowEdge(BaseModel):
    source: str
    target: str
    label: str | None = None


class WorkflowVisualization(BaseModel):
    """Safe graph description for the dynamic frontend; never includes secrets."""

    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    tracing_enabled: bool
    tracing_project: str | None = None


class WorkflowAnalysisExecution(BaseModel):
    analysis_run_id: str
    impact_report: ImpactReport
    remediation_plan: RemediationPlan
    graph: WorkflowVisualization


class WorkflowCritiqueExecution(BaseModel):
    critique: AdvisoryCritique
    graph: WorkflowVisualization


class WorkflowJudgingExecution(BaseModel):
    judging: StoredJudgingResult
    graph: WorkflowVisualization


class CatalogNode(BaseModel):
    """One safe DataHub asset projection for the interactive catalog graph."""

    urn: str
    label: str
    entity_type: str = "UNKNOWN"
    platform_urn: str | None = None
    owner_urns: list[str] = Field(default_factory=list)
    degree: int | None = None
    recent_actions: list["CatalogAction"] = Field(default_factory=list)


class CatalogEdge(BaseModel):
    source_urn: str
    target_urn: str
    direction: str
    hops: int = Field(ge=1, le=5)


class CatalogGraph(BaseModel):
    """Bounded catalog projection; this is not an unbounded DataHub export."""

    nodes: list[CatalogNode]
    edges: list[CatalogEdge]
    query: str | None = None
    max_hops: int | None = None
    truncated: bool = False


class CatalogAction(BaseModel):
    """A public, local LineageGuard activity associated with a catalog node."""

    timestamp: datetime
    action: str
    detail: str


class CatalogCacheState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    READY = "READY"
    STALE = "STALE"
    FAILED = "FAILED"


class CatalogCacheStatus(BaseModel):
    state: CatalogCacheState = CatalogCacheState.IDLE
    loaded_assets: int = Field(default=0, ge=0)
    loaded_edges: int = Field(default=0, ge=0)
    message: str = "Catalog cache has not started."
    last_updated_at: datetime | None = None
    refresh_reason: str | None = None
    refresh_started_at: datetime | None = None
    last_checked_at: datetime | None = None
    refresh_in_progress: bool = False
    consecutive_failures: int = Field(default=0, ge=0)
    last_error: str | None = None
    detected_change: str | None = None
    generation: int = Field(default=0, ge=0)


class CatalogCacheSnapshot(BaseModel):
    """Server-side 3D catalog cache plus safe freshness metadata."""

    status: CatalogCacheStatus
    graph: CatalogGraph


class RagIndexState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RagIndexStatus(BaseModel):
    """Safe status for the metadata-only Qdrant index."""

    state: RagIndexState = RagIndexState.IDLE
    indexed_assets: int = Field(default=0, ge=0)
    total_assets: int = Field(default=0, ge=0)
    message: str = "Index not started."
    updated_at: datetime | None = None
    # Re-indexing is non-blocking when a prior Qdrant collection is usable.
    query_available: bool = False


class RagCitation(BaseModel):
    urn: str
    label: str
    entity_type: str
    platform_urn: str | None = None
    source: str
    score: float | None = None


class AgentEvidence(BaseModel):
    """A compact, user-visible fact returned by an allowlisted MCP tool."""

    id: str
    kind: Literal["search", "schema", "lineage"]
    asset_urn: str
    summary: str
    facts: list[str] = Field(default_factory=list)


class FactualClaimVerification(BaseModel):
    """Public, deterministic support decision for one answer assertion."""

    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    supported: bool
    reason: str


class VerificationResult(BaseModel):
    """Deterministic evidence-bound verification, not hidden chain-of-thought."""

    passed: bool
    checks: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    claims: list[FactualClaimVerification] = Field(default_factory=list)
    factual_claim_count: int = Field(default=0, ge=0)
    supported_claim_count: int = Field(default=0, ge=0)
    claim_coverage: float = Field(default=0.0, ge=0.0, le=1.0)


class ChatActionType(StrEnum):
    NONE = "NONE"
    ANALYZE_IMPACT = "ANALYZE_IMPACT"
    HITL_WRITEBACK = "HITL_WRITEBACK"


class ChatActionProposal(BaseModel):
    action: ChatActionType = ChatActionType.NONE
    change_type: ChangeType | None = None
    requires_confirmation: bool = False
    reason: str
    required_fields: list[str] = Field(default_factory=list)


class AgenticTraceStep(BaseModel):
    """Auditable, compact execution trace; never private chain-of-thought."""

    id: str
    label: str
    status: str
    detail: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    max_sources: int = Field(default=6, ge=1, le=12)
    session_id: str | None = Field(default=None, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    memory_enabled: bool = True
    # A browser may submit a prior live-MCP candidate after the user resolves
    # an ambiguity. It is always re-checked against the new MCP search.
    selected_asset_urn: str | None = Field(default=None, pattern=r"^urn:li:")


class ChatMemoryStatus(BaseModel):
    """Privacy-safe status of the bounded conversation memory."""

    session_id: str | None = None
    enabled: bool = False
    message_count: int = Field(default=0, ge=0)
    max_turns: int = Field(default=0, ge=0)
    last_updated_at: datetime | None = None


class ChatTargetResolution(BaseModel):
    """Public outcome of resolving an asset before sensitive metadata reads."""

    status: Literal["NOT_REQUIRED", "RESOLVED", "AMBIGUOUS", "NOT_FOUND"]
    detail: str
    targets: list[RagCitation] = Field(default_factory=list)


class ModelUsage(BaseModel):
    """Safe provider metering for a single agentic chat run."""

    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class ChatResponse(BaseModel):
    answer: str
    citations: list[RagCitation]
    verification_note: str
    action_proposal: ChatActionProposal
    agent_trace: list[AgenticTraceStep] = Field(default_factory=list)
    evidence: list[AgentEvidence] = Field(default_factory=list)
    verification: VerificationResult | None = None
    memory: ChatMemoryStatus | None = None
    target_resolution: ChatTargetResolution | None = None
    active_verified_asset: RagCitation | None = None
    analysis_handoff_id: str | None = None
    analysis_handoff_expires_at: datetime | None = None
    model_usage: ModelUsage | None = None


class ChatAnalysisRequest(BaseModel):
    """Explicitly confirmed, read-only handoff from chat to the impact workflow."""

    change_request: ChangeRequest
    confirmed: bool = False
    handoff_id: str = Field(min_length=16, max_length=100)
    session_id: str = Field(
        min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )
