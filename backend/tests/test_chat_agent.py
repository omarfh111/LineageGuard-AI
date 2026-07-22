import pytest

from app.domain.contracts import ChatActionType, ChatRequest, RagCitation
from app.services.chat_agent import HybridChatAgent, KeywordPlanningProvider, _propose_action


class FakeIndex:
    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        assert question == "Which assets depend on orders?"
        assert limit == 6
        return [
            RagCitation(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)",
                label="shop.orders",
                entity_type="DATASET",
                platform_urn="urn:li:dataPlatform:dbt",
                source="qdrant_metadata_index",
                score=0.91,
            )
        ]


class FakeDataHub:
    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        assert query == "Which assets depend on orders"
        assert (num_results, offset) == (10, 0)
        return {
            "structuredContent": {
                "searchResults": [
                    {
                        "entity": {
                            "urn": "urn:li:dataset:(urn:li:dataPlatform:tableau,orders_dashboard,PROD)",
                            "type": "DASHBOARD",
                            "properties": {"name": "orders_dashboard"},
                            "platform": {"urn": "urn:li:dataPlatform:tableau"},
                        }
                    }
                ]
            }
        }

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        assert urn.endswith("orders_dashboard,PROD)")
        assert (direction, max_hops, max_results) == ("DOWNSTREAM", 1, 25)
        return {"structuredContent": {"downstreams": {"searchResults": []}}}


class FakeCompletion:
    async def answer(self, question: str, sources: list[RagCitation], evidence: list) -> str:
        assert question == "Which assets depend on orders?"
        assert {source.source for source in sources} == {
            "qdrant_metadata_index", "datahub_mcp_live"
        }
        assert evidence[0].id == "E1"
        lineage = next(item for item in evidence if item.kind == "lineage")
        return f"orders_dashboard is a live DataHub match. [E1] [{lineage.id}]"


class SchemaIndex:
    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        return [
            RagCitation(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)",
                label="shop.orders", entity_type="DATASET", source="qdrant_metadata_index"
            )
        ]


class SchemaDataHub:
    def __init__(self) -> None:
        self.schema_calls: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        return {"structuredContent": {"searchResults": [{"entity": {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)",
            "type": "DATASET", "properties": {"name": "shop.orders"},
        }}]}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": [{"fieldPath": "order_id"}]}}


class AnyCompletion:
    async def answer(self, question: str, sources: list[RagCitation], evidence: list) -> str:
        schema = next(item for item in evidence if item.kind == "schema")
        return f"Grounded metadata answer. [E1] [{schema.id}]"


@pytest.mark.asyncio
async def test_hybrid_chat_retrieves_then_verifies_with_datahub_mcp() -> None:
    response = await HybridChatAgent(
        FakeDataHub(), FakeIndex(), completion=FakeCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Which assets depend on orders?"))

    assert response.answer.startswith("orders_dashboard is a live DataHub match. [E1] [E-lineage-")
    assert len(response.citations) == 2
    assert response.citations[0].source == "datahub_mcp_live"
    assert response.verification and response.verification.passed
    assert response.action_proposal.action == ChatActionType.NONE
    assert [step.id for step in response.agent_trace] == [
        "planning", "retriever", "mcp_tools", "reasoning", "verification"
    ]


def test_chat_proposes_read_only_analysis_for_schema_change() -> None:
    proposal = _propose_action("Please drop the customer_status column")

    assert proposal.action == ChatActionType.ANALYZE_IMPACT
    assert proposal.requires_confirmation
    assert "asset_urn" in proposal.required_fields


def test_chat_never_proposes_a_direct_write() -> None:
    proposal = _propose_action("Save a documentation update to DataHub")

    assert proposal.action == ChatActionType.HITL_WRITEBACK
    assert proposal.requires_confirmation


@pytest.mark.asyncio
async def test_agentic_router_invokes_schema_tool_only_for_schema_question() -> None:
    datahub = SchemaDataHub()
    response = await HybridChatAgent(
        datahub, SchemaIndex(), completion=AnyCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Show the schema and columns of orders"))

    assert datahub.schema_calls == ["urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"]
    tool_trace = next(step for step in response.agent_trace if step.id == "mcp_tools")
    assert "list_schema_fields" in tool_trace.detail
    schema_evidence = next(item for item in response.evidence if item.kind == "schema")
    assert schema_evidence.facts == ["column=order_id"]
    assert response.verification and response.verification.passed
