"""Read-only remediation-plan generation endpoint."""

from fastapi import APIRouter

from app.domain.contracts import ImpactReport, RemediationPlan
from app.services.remediation_planner import DeterministicRemediationPlanner

router = APIRouter(prefix="/remediations", tags=["remediation"])


@router.post("/plan", response_model=RemediationPlan)
def generate_remediation_plan(report: ImpactReport) -> RemediationPlan:
    """Generate guidance only; no warehouse or DataHub mutation is performed."""

    return DeterministicRemediationPlanner().plan(report)
