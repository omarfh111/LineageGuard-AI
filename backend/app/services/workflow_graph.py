"""LangGraph orchestration for LineageGuard's governed workflow.

The graph is intentionally composed of narrow, existing services. It does not
give LLMs tools and it never bypasses the separate HITL write-back boundary.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings, get_settings
from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import (
    AdvisoryCritique,
    ChangeRequest,
    CritiqueRequest,
    JudgingRequest,
    JudgingResult,
    RemediationPlan,
    StoredJudgingResult,
    WorkflowAnalysisExecution,
    WorkflowCritiqueExecution,
    WorkflowEdge,
    WorkflowJudgingExecution,
    WorkflowNode,
    WorkflowNodeStatus,
    WorkflowVisualization,
)
from app.services.impact_analysis import ImpactAnalysisService
from app.services.judging import JudgingService
from app.services.metadata_investigator import MetadataInvestigation, MetadataInvestigator
from app.services.nvidia_critic import NvidiaCritic
from app.services.request_interpreter import RequestInterpreter
from app.services.remediation_planner import DeterministicRemediationPlanner
from app.services.run_store import analysis_store, run_store


class WorkflowState(TypedDict):
    operation: Literal["ANALYZE", "CRITIQUE", "JUDGE"]
    change_request: NotRequired[ChangeRequest]
    interpreted_request: NotRequired[ChangeRequest]
    metadata_investigation: NotRequired[MetadataInvestigation]
    critique_request: NotRequired[CritiqueRequest]
    judging_request: NotRequired[JudgingRequest]
    impact_report: NotRequired[Any]
    remediation_plan: NotRequired[Any]
    critique: NotRequired[Any]
    judging_result: NotRequired[Any]
    run_id: NotRequired[str]
    node_statuses: dict[str, str]


class LineageGuardWorkflow:
    """Real StateGraph implementation for the three manually triggered paths."""

    def __init__(
        self,
        client: DataHubMcpClient | None = None,
        settings: Settings | None = None,
        critic: NvidiaCritic | None = None,
        judges: JudgingService | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._critic = critic
        self._judges = judges
        self._graph = self._build()

    async def analyze(self, request: ChangeRequest) -> WorkflowAnalysisExecution:
        state = await self._graph.ainvoke(
            {
                "operation": "ANALYZE",
                "change_request": request,
                "node_statuses": {"request": "RUNNING"},
            },
            {"run_name": "lineageguard-impact-plan", "tags": ["lineageguard", "read-only"]},
        )
        report = state["impact_report"]
        plan = state["remediation_plan"]
        return WorkflowAnalysisExecution(
            analysis_run_id=analysis_store.save(report, plan),
            impact_report=report,
            remediation_plan=plan,
            graph=self.visualization(state["node_statuses"]),
        )

    def restore_analysis(self, run_id: str) -> WorkflowAnalysisExecution | None:
        """Rebuild read-only UI state from an immutable server snapshot."""

        snapshot = analysis_store.restore(run_id)
        if snapshot is None:
            return None
        report, plan = snapshot
        return WorkflowAnalysisExecution(
            analysis_run_id=run_id,
            impact_report=report,
            remediation_plan=plan,
            graph=self.visualization(
                {
                    "request": "COMPLETED",
                    "metadata": "COMPLETED",
                    "impact": "COMPLETED",
                    "plan": "COMPLETED",
                }
            ),
        )

    async def critique(self, request: CritiqueRequest) -> WorkflowCritiqueExecution:
        state = await self._graph.ainvoke(
            {
                "operation": "CRITIQUE",
                "critique_request": request,
                "node_statuses": {"request": "COMPLETED", "metadata": "COMPLETED", "impact": "COMPLETED", "plan": "COMPLETED", "critic": "RUNNING"},
            },
            {"run_name": "lineageguard-advisory-critique", "tags": ["lineageguard", "advisory"]},
        )
        return WorkflowCritiqueExecution(
            critique=state["critique"],
            graph=self.visualization(state["node_statuses"]),
        )

    async def judge(self, request: JudgingRequest) -> WorkflowJudgingExecution:
        state = await self._graph.ainvoke(
            {
                "operation": "JUDGE",
                "judging_request": request,
                "node_statuses": {"request": "COMPLETED", "metadata": "COMPLETED", "impact": "COMPLETED", "plan": "COMPLETED", "judges": "RUNNING"},
            },
            {"run_name": "lineageguard-independent-judges", "tags": ["lineageguard", "human-review"]},
        )
        result = StoredJudgingResult(run_id=state["run_id"], result=state["judging_result"])
        return WorkflowJudgingExecution(
            judging=result,
            graph=self.visualization(state["node_statuses"]),
        )

    def visualization(self, statuses: dict[str, str] | None = None) -> WorkflowVisualization:
        statuses = statuses or {}
        def status(node_id: str) -> WorkflowNodeStatus:
            value = statuses.get(node_id, "PENDING")
            return WorkflowNodeStatus(value)

        return WorkflowVisualization(
            nodes=[
                WorkflowNode(id="request", label="Interpréteur de demande", kind="deterministic", status=status("request"), description="Normalise la demande validée sans LLM ni mutation."),
                WorkflowNode(id="metadata", label="Investigation DataHub", kind="read-only", status=status("metadata"), description="Schema et lineage recuperes via MCP en lecture seule."),
                WorkflowNode(id="impact", label="Impact DataHub", kind="read-only", status=status("impact"), description="MCP en lecture seule et preuves de lineage."),
                WorkflowNode(id="plan", label="Plan deterministe", kind="deterministic", status=status("plan"), description="Plan et rollback non executables."),
                WorkflowNode(id="critic", label="Critique NVIDIA", kind="advisory", status=status("critic"), description="Avis consultatif, sans outil DataHub."),
                WorkflowNode(id="judges", label="OpenAI + Groq", kind="independent", status=status("judges"), description="Deux jugements independants apres Gate 0."),
                WorkflowNode(id="hitl", label="Validation HITL", kind="human", status=status("hitl"), description="Toute ecriture exige une approbation humaine."),
            ],
            edges=[
                WorkflowEdge(source="request", target="metadata"),
                WorkflowEdge(source="metadata", target="impact"),
                WorkflowEdge(source="impact", target="plan"),
                WorkflowEdge(source="plan", target="critic", label="manuel"),
                WorkflowEdge(source="plan", target="judges", label="manuel"),
                WorkflowEdge(source="judges", target="hitl", label="double PASS"),
            ],
            tracing_enabled=self._settings.langsmith_tracing_enabled,
            tracing_project=self._settings.langsmith_project if self._settings.langsmith_tracing_enabled else None,
        )

    def _build(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("request", self._interpret_request)
        graph.add_node("metadata", self._investigate_metadata)
        graph.add_node("impact", self._analyze_impact)
        graph.add_node("plan", self._build_plan)
        graph.add_node("critic", self._run_critic)
        graph.add_node("judges", self._run_judges)
        graph.add_conditional_edges(START, self._select_operation, {"request": "request", "critic": "critic", "judges": "judges"})
        graph.add_edge("request", "metadata")
        graph.add_edge("metadata", "impact")
        graph.add_edge("impact", "plan")
        graph.add_edge("plan", END)
        graph.add_edge("critic", END)
        graph.add_edge("judges", END)
        return graph.compile()

    def _select_operation(self, state: WorkflowState) -> str:
        return {"ANALYZE": "request", "CRITIQUE": "critic", "JUDGE": "judges"}[state["operation"]]

    def _interpret_request(self, state: WorkflowState) -> dict[str, object]:
        request = RequestInterpreter().interpret(state["change_request"])
        statuses = dict(state["node_statuses"])
        statuses["request"] = "COMPLETED"
        statuses["metadata"] = "RUNNING"
        return {"interpreted_request": request, "node_statuses": statuses}

    async def _investigate_metadata(self, state: WorkflowState) -> dict[str, object]:
        if self._client is None:
            raise RuntimeError("DataHub client is required for metadata investigation")
        investigation = await MetadataInvestigator(self._client).investigate(state["interpreted_request"])
        statuses = dict(state["node_statuses"])
        statuses["metadata"] = "COMPLETED"
        statuses["impact"] = "RUNNING"
        return {"metadata_investigation": investigation, "node_statuses": statuses}

    async def _analyze_impact(self, state: WorkflowState) -> dict[str, object]:
        if self._client is None:
            raise RuntimeError("DataHub client is required for impact analysis")
        report = await ImpactAnalysisService(self._client).analyze(
            state["interpreted_request"], state["metadata_investigation"]
        )
        statuses = dict(state["node_statuses"])
        statuses["impact"] = "COMPLETED"
        statuses["plan"] = "RUNNING"
        return {"impact_report": report, "node_statuses": statuses}

    def _build_plan(self, state: WorkflowState) -> dict[str, object]:
        plan = DeterministicRemediationPlanner().plan(state["impact_report"])
        statuses = dict(state["node_statuses"])
        statuses["plan"] = "COMPLETED"
        return {"remediation_plan": plan, "node_statuses": statuses}

    async def _run_critic(self, state: WorkflowState) -> dict[str, object]:
        critic = self._critic or NvidiaCritic(self._settings)
        critique = await critic.critique(state["critique_request"])
        statuses = dict(state["node_statuses"])
        statuses["critic"] = "COMPLETED"
        return {"critique": critique, "node_statuses": statuses}

    async def _run_judges(self, state: WorkflowState) -> dict[str, object]:
        service = self._judges or JudgingService(settings=self._settings)
        request = state["judging_request"]
        result: JudgingResult = await service.evaluate(request)
        statuses = dict(state["node_statuses"])
        statuses["judges"] = "COMPLETED"
        if result.aggregate_decision and result.aggregate_decision.human_review_required:
            statuses["hitl"] = "AWAITING_HUMAN"
        return {"judging_result": result, "run_id": run_store.save(request, result), "node_statuses": statuses}
