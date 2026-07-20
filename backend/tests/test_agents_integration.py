"""End-to-end coverage for the deterministic workflow agents."""

import pytest

from app.domain.contracts import AdvisoryCritique, ChangeRequest, CritiqueRequest, JudgeProvider, JudgeStatus
from app.services.judging import JudgingService
from app.services.workflow_graph import LineageGuardWorkflow
from test_impact_analysis import FakeDataHubMcpClient, request_payload
from test_judging import FakeJudge, judging_request, verdict


class FakeCritic:
    async def critique(self, request: CritiqueRequest) -> AdvisoryCritique:
        return AdvisoryCritique(
            provider="nvidia", model="test-model", summary="No blocking issue.",
            issues=[], recommended_revisions=[], confidence=1,
        )


@pytest.mark.asyncio
async def test_analysis_runs_request_metadata_impact_and_planning_agents_once() -> None:
    execution = await LineageGuardWorkflow(client=FakeDataHubMcpClient()).analyze(
        ChangeRequest.model_validate(request_payload())
    )

    statuses = {node.id: node.status.value for node in execution.graph.nodes}
    assert statuses == {
        "request": "COMPLETED",
        "metadata": "COMPLETED",
        "impact": "COMPLETED",
        "plan": "COMPLETED",
        "critic": "PENDING",
        "judges": "PENDING",
        "hitl": "PENDING",
    }
    assert execution.impact_report.evidence_bundle.items[0].tool == "list_schema_fields"
    assert execution.remediation_plan.execution_status == "NOT_EXECUTED"


@pytest.mark.asyncio
async def test_advisory_and_independent_judge_agents_are_wired_to_langgraph() -> None:
    request = judging_request()
    workflow = LineageGuardWorkflow(
        critic=FakeCritic(),
        judges=JudgingService(
            FakeJudge(verdict(JudgeProvider.OPENAI, JudgeStatus.PASS)),
            FakeJudge(verdict(JudgeProvider.GROQ, JudgeStatus.PASS)),
        ),
    )

    critique = await workflow.critique(
        CritiqueRequest(impact_report=request.impact_report, remediation_plan=request.remediation_plan)
    )
    judged = await workflow.judge(request)

    assert critique.graph.nodes[4].status.value == "COMPLETED"
    assert judged.judging.result.aggregate_decision.decision == "FINALIZE_READ_ONLY"
