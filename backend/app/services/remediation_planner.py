"""Deterministic remediation and business-rollback planning without execution."""

from __future__ import annotations

from app.domain.contracts import (
    BusinessRollbackPlan,
    ChangeType,
    ImpactReport,
    PlanStep,
    RecommendedTest,
    RemediationPlan,
)


class DeterministicRemediationPlanner:
    """Create conservative, evidence-scoped guidance for a proposed change."""

    def plan(self, report: ImpactReport) -> RemediationPlan:
        request = report.request
        impacted_urns = [impact.asset_urn for impact in report.impacted_assets]
        owners = sorted(
            {
                owner
                for impact in report.impacted_assets
                for owner in impact.owner_urns
            }
        )
        tests = _recommended_tests(request.change_type, request.asset_urn, impacted_urns)
        return RemediationPlan(
            source_asset_urn=request.asset_urn,
            change_type=request.change_type,
            migration_steps=_migration_steps(report),
            backward_compatible=_compatibility(request.change_type)[0],
            forward_compatible=_compatibility(request.change_type)[1],
            deprecation_period=_deprecation_period(request.change_type),
            recommended_tests=tests,
            downstream_checks=[
                f"Validate the {len(impacted_urns)} evidenced downstream asset(s) before deployment.",
                "Confirm that each owner has reviewed impacts relevant to their asset.",
                "Re-run the read-only DataHub impact analysis before the final deployment decision.",
            ],
            owners_to_notify=owners,
            deployment_conditions=[
                "The evidence-backed impact report is current for the target environment.",
                "All recommended tests pass in a non-production environment.",
                "Required owner approvals are recorded outside this service.",
                "A human explicitly authorizes any external schema change.",
            ],
            stop_conditions=[
                "A downstream validation or contract test fails.",
                "A critical downstream owner has not approved the change.",
                "The schema differs from the snapshot represented by the impact report.",
            ],
            rollback_plan=BusinessRollbackPlan(
                trigger_conditions=[
                    "A downstream contract, SQL, or dbt test fails after deployment.",
                    "A consumer cannot read the new schema or produces incorrect results.",
                ],
                preservation_steps=[
                    "Preserve the pre-change schema definition and consumer contracts before deployment.",
                    "Keep the prior compatible field or view available through the deprecation period when applicable.",
                ],
                reversal_steps=_rollback_steps(request.change_type, request.column_name),
                dependency_restore_steps=[
                    "Restore each validated downstream consumer to the preserved contract.",
                    "Re-run the impacted downstream checks and record their outcomes.",
                ],
                post_rollback_tests=tests,
                responsible_owner_urns=owners,
                success_criteria=[
                    "The original schema contract is available to downstream consumers.",
                    "All post-rollback tests pass.",
                    "Owners confirm restoration of their affected assets.",
                ],
            ),
        )


def _migration_steps(report: ImpactReport) -> list[PlanStep]:
    request = report.request
    impacted_urns = [impact.asset_urn for impact in report.impacted_assets]
    steps = [
        PlanStep(
            order=1,
            action="Review the evidence-backed impact report with affected owners.",
            rationale="The plan is limited to assets returned by read-only DataHub lineage.",
            affected_asset_urns=[request.asset_urn, *impacted_urns],
        ),
        PlanStep(
            order=2,
            action=_consumer_migration_action(request.change_type, request.column_name, request.new_value),
            rationale="Consumers must be compatible before any external schema change is authorized.",
            affected_asset_urns=impacted_urns,
        ),
        PlanStep(
            order=3,
            action="Run the recommended schema and downstream validation tests.",
            rationale="No destructive action may proceed with failing validation.",
            affected_asset_urns=[request.asset_urn, *impacted_urns],
        ),
        PlanStep(
            order=4,
            action="Request human approval for the externally executed schema change.",
            rationale="LineageGuard only proposes this action; it does not execute it.",
            affected_asset_urns=[request.asset_urn],
        ),
    ]
    return steps


def _consumer_migration_action(
    change_type: ChangeType, column_name: str | None, new_value: str | None
) -> str:
    if change_type is ChangeType.ADD_COLUMN:
        return (
            f"Verify whether consumers ignore or tolerate the proposed new column "
            f"{column_name or '(name pending)'} before any external schema change."
        )
    if change_type is ChangeType.RENAME_COLUMN:
        return f"Migrate consumers from {column_name} to {new_value} while retaining a compatibility alias."
    if change_type is ChangeType.CHANGE_COLUMN_TYPE:
        return f"Update consumers of {column_name} to handle the proposed type {new_value}."
    return f"Remove consumer references to {column_name} before proposing its removal."


def _compatibility(change_type: ChangeType) -> tuple[bool | None, bool | None]:
    """Do not claim compatibility without a consumer contract and column-type proof."""

    if change_type is ChangeType.ADD_COLUMN:
        return None, None
    if change_type is ChangeType.RENAME_COLUMN:
        return None, None
    if change_type is ChangeType.CHANGE_COLUMN_TYPE:
        return False, False
    return False, False


def _deprecation_period(change_type: ChangeType) -> str | None:
    if change_type in {ChangeType.RENAME_COLUMN, ChangeType.DROP_COLUMN}:
        return "Required; keep the prior contract until downstream owners confirm migration."
    return None


def _recommended_tests(
    change_type: ChangeType, source_urn: str, impacted_urns: list[str]
) -> list[RecommendedTest]:
    return [
        RecommendedTest(
            name="Source schema contract check",
            category="SCHEMA",
            purpose=f"Confirm the intended {change_type} contract for the source asset.",
            affected_asset_urns=[source_urn],
        ),
        RecommendedTest(
            name="Downstream SQL or dbt validation",
            category="DOWNSTREAM",
            purpose="Verify that each evidenced downstream consumer remains compatible.",
            affected_asset_urns=impacted_urns,
        ),
        RecommendedTest(
            name="Read-only lineage refresh",
            category="DATAHUB",
            purpose="Confirm the downstream inventory before approving deployment or rollback.",
            affected_asset_urns=[source_urn, *impacted_urns],
        ),
    ]


def _rollback_steps(change_type: ChangeType, column_name: str | None) -> list[str]:
    if change_type is ChangeType.ADD_COLUMN:
        return [
            "Use an owner-approved external migration to stop exposing the added column "
            f"{column_name or '(name pending)'}, only after consumer contracts are preserved."
        ]
    if change_type is ChangeType.RENAME_COLUMN:
        return ["Restore the previous column name or compatibility alias."]
    if change_type is ChangeType.CHANGE_COLUMN_TYPE:
        return ["Restore the preserved compatible type and conversion path."]
    return [f"Restore the preserved column {column_name} and its documented contract."]
