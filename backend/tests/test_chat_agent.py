import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.domain.contracts import AgentEvidence, ChatActionType, ChatRequest, RagCitation
from app.services.chat_agent import (
    HybridChatAgent,
    KeywordPlanningProvider,
    OpenAIChatCompletionProvider,
    OpenAIPlanningProvider,
    _verify_factual_claims,
    _propose_action,
    _filter_general_matches,
    _search_terms_for_question,
)


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
        assert (num_results, offset) == (10, 0)
        if query == "shop.orders":
            return {
                "structuredContent": {
                    "searchResults": [
                        {
                            "entity": {
                                "urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)",
                                "type": "DATASET",
                                "properties": {"name": "shop.orders"},
                                "platform": {"urn": "urn:li:dataPlatform:dbt"},
                            }
                        }
                    ]
                }
            }
        assert query == "orders"
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
        assert urn.endswith("shop.orders,PROD)")
        assert (direction, max_hops, max_results) == ("DOWNSTREAM", 1, 25)
        return {
            "structuredContent": {
                "downstreams": {
                    "searchResults": [
                        {
                            "entity": {
                                "urn": "urn:li:dashboard:(tableau,downstream_orders)",
                                "type": "DASHBOARD",
                                "properties": {"name": "downstream_orders"},
                            },
                            "degree": 1,
                        }
                    ]
                }
            }
        }


class FakeCompletion:
    async def answer(self, question: str, sources: list[RagCitation], evidence: list) -> str:
        assert question == "Which assets depend on orders?"
        # A target-specific answer may only use the resolved live MCP asset.
        assert {source.source for source in sources} == {
            "datahub_mcp_live_qdrant_guided",
            "datahub_mcp_live",
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
        return f"{schema.facts[0]}. [{schema.id}]"


class NoMatchDataHub:
    def __init__(self) -> None:
        self.schema_calls: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        return {"structuredContent": {"searchResults": []}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": []}}


class GuidedAliasIndex:
    def __init__(self, urn: str, label: str = "shop.orders", score: float = 0.94) -> None:
        self.candidate = RagCitation(
            urn=urn,
            label=label,
            entity_type="DATASET",
            platform_urn="urn:li:dataPlatform:dbt",
            source="qdrant_metadata_index",
            score=score,
        )

    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        return [self.candidate]


class GuidedAliasDataHub:
    urn = "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)"

    def __init__(self, *, confirm_exact: bool = True) -> None:
        self.confirm_exact = confirm_exact
        self.schema_calls: list[str] = []
        self.search_queries: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        self.search_queries.append(query)
        if query != "shop.orders":
            return {"structuredContent": {"searchResults": []}}
        urn = self.urn if self.confirm_exact else self.urn.replace("shop.orders", "shop.stale_orders")
        return {"structuredContent": {"searchResults": [{"entity": {
            "urn": urn,
            "type": "DATASET",
            "properties": {"name": "shop.orders"},
            "platform": {"urn": "urn:li:dataPlatform:dbt"},
        }}]}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": [{"fieldPath": "order_id", "nativeDataType": "NUMBER"}]}}


class ManyCandidatesIndex:
    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        return [
            RagCitation(
                urn=f"urn:li:dataset:(urn:li:dataPlatform:dbt,shop.asset_{index},PROD)",
                label=f"shop.asset_{index}",
                entity_type="DATASET",
                source="qdrant_metadata_index",
                score=0.95 - index / 100,
            )
            for index in range(8)
        ]


class SchemaFieldParentIndex:
    parent = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.sales.orders,PROD)"

    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        return [
            RagCitation(
                urn=f"urn:li:schemaField:({self.parent},{field})",
                label=field,
                entity_type="SCHEMAFIELD",
                platform_urn="urn:li:dataPlatform:snowflake",
                source="qdrant_metadata_index",
                score=score,
            )
            for field, score in (("order_id", 0.81), ("order_total", 0.79))
        ]


class SchemaFieldParentDataHub:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.schema_calls: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        self.search_queries.append(query)
        if query != "db.sales.orders":
            return {"structuredContent": {"searchResults": []}}
        return {"structuredContent": {"searchResults": [{"entity": {
            "urn": SchemaFieldParentIndex.parent,
            "type": "DATASET",
            "properties": {"name": "db.sales.orders"},
            "platform": {"urn": "urn:li:dataPlatform:snowflake"},
        }}]}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": [{"fieldPath": "order_id", "nativeDataType": "NUMBER"}]}}


class BoundedConfirmationDataHub:
    def __init__(self) -> None:
        self.batch_size = 0

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        return {"structuredContent": {"searchResults": []}}

    async def search_many(self, requests: list[tuple[str, int, int]]) -> list[dict]:
        self.batch_size = len(requests)
        return [
            {"structuredContent": {"searchResults": [{"entity": {
                "urn": f"urn:li:dataset:(urn:li:dataPlatform:dbt,{label},PROD)",
                "type": "DATASET",
                "properties": {"name": label},
            }}]}}
            for label, _, _ in requests
        ]


class SafeNoMatchCompletion:
    async def answer(self, question: str, sources: list[RagCitation], evidence: list) -> str:
        return "No live match was found."


class SlowCompletions:
    async def create(self, **_: object) -> object:
        await asyncio.sleep(0.1)
        raise AssertionError("The configured timeout should cancel this call")


class UnavailableIndex:
    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        raise RuntimeError("embedding provider unavailable")


class SearchCompletion:
    async def answer(self, question: str, sources: list[RagCitation], evidence: list) -> str:
        return f"Verified live search result. [{evidence[0].id}]"


class SlowSearchDataHub:
    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        await asyncio.sleep(0.1)
        raise AssertionError("The configured MCP timeout should cancel this call")


def chat_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite://",
        datahub_gms_url="http://datahub",
        datahub_gms_token=None,
        openai_api_key="test-key",
        chat_model="test-model",
        chat_timeout_seconds=0.01,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_slow_chat_model_falls_back_to_named_mcp_evidence() -> None:
    provider = OpenAIChatCompletionProvider(chat_settings())
    provider._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SlowCompletions())
    )
    evidence = [
        AgentEvidence(
            id="E-lineage-orders",
            kind="lineage",
            asset_urn="urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)",
            summary="Verified downstream lineage for orders.",
            facts=["downstream=orders_dashboard"],
        )
    ]

    answer = await provider.answer("Show downstream lineage", [], evidence)

    assert provider.last_mode == "deterministic_evidence_fallback"
    assert "[E-lineage-orders]" in answer
    assert "downstream=orders_dashboard" in answer


@pytest.mark.asyncio
async def test_slow_planner_uses_bounded_keyword_fallback() -> None:
    provider = OpenAIPlanningProvider(chat_settings())
    provider._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SlowCompletions())
    )

    plan = await provider.plan("Show the downstream lineage of orders")

    assert provider.last_mode == "deterministic_fallback"
    assert plan.search_terms == "orders"
    assert plan.need_lineage


@pytest.mark.asyncio
async def test_unavailable_qdrant_retrieval_continues_with_live_mcp() -> None:
    response = await HybridChatAgent(
        FakeDataHub(),
        UnavailableIndex(),
        completion=SearchCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Tell me about orders"))

    retriever = next(step for step in response.agent_trace if step.id == "retriever")
    assert retriever.status == "LIMITED"
    assert response.verification and response.verification.passed
    assert response.citations[0].source == "datahub_mcp_live"


@pytest.mark.asyncio
async def test_slow_mcp_search_fails_closed_without_target_handoff() -> None:
    response = await HybridChatAgent(
        SlowSearchDataHub(),
        SchemaIndex(),
        settings=chat_settings(),
        completion=SafeNoMatchCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Drop customer_status from orders"))

    assert response.target_resolution
    assert response.target_resolution.status == "NOT_FOUND"
    assert response.target_resolution.targets == []
    assert response.action_proposal.action == ChatActionType.ANALYZE_IMPACT
    assert response.active_verified_asset is None
    mcp = next(step for step in response.agent_trace if step.id == "mcp_tools")
    assert mcp.status == "LIMITED"


@pytest.mark.asyncio
async def test_hybrid_chat_retrieves_then_verifies_with_datahub_mcp() -> None:
    response = await HybridChatAgent(
        FakeDataHub(), FakeIndex(), completion=FakeCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Which assets depend on orders?"))

    assert response.answer.startswith("- DataHub downstream lineage for shop.orders")
    assert "[E-lineage-" in response.answer
    assert len(response.citations) == 2
    assert response.citations[0].source == "datahub_mcp_live_qdrant_guided"
    assert response.target_resolution is not None
    assert len(response.target_resolution.targets) == 1
    assert response.target_resolution.targets[0].label == "shop.orders"
    tool_trace = next(step for step in response.agent_trace if step.id == "mcp_tools")
    assert "Qdrant-guided exact MCP confirmations: 1" in tool_trace.detail
    assert response.verification and response.verification.passed
    assert response.action_proposal.action == ChatActionType.NONE
    assert [step.id for step in response.agent_trace] == [
        "planning", "retriever", "mcp_tools", "target", "reasoning", "verification"
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


def test_keyword_planner_extracts_an_asset_name_from_a_natural_language_question() -> None:
    plan = KeywordPlanningProvider().plan_sync("What datasets named orders exist in the DataHub catalog?")

    assert plan.search_terms == "orders"


def test_keyword_planner_removes_conversational_words_from_asset_query() -> None:
    plan = KeywordPlanningProvider().plan_sync("Tell me about the orders dataset")

    assert plan.search_terms == "orders"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Find all datasets named orders.", "orders"),
        ("Find the Snowflake orders dataset.", "orders"),
        ("List every dataset called product_categories.", "product_categories"),
        ("Get downstream lineage for the Postgres customers dataset.", "customers"),
        ("List the schema fields and types for the Postgres customers dataset.", "customers"),
        ("What fields exist in the Snowflake order_details dataset?", "order_details"),
    ],
)
def test_keyword_planner_normalizes_professional_benchmark_phrasing(
    question: str, expected: str
) -> None:
    assert KeywordPlanningProvider().plan_sync(question).search_terms == expected


def test_direct_asset_extraction_strips_sentence_punctuation() -> None:
    assert _search_terms_for_question(
        "Find all datasets named orders.", "orders.", None
    ) == "orders"


def test_general_catalog_matches_honor_exact_name_and_platform() -> None:
    matches = [
        RagCitation(
            urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.orders,PROD)",
            label="ORDERS",
            entity_type="DATASET",
            platform_urn="urn:li:dataPlatform:snowflake",
            source="datahub_mcp_live",
        ),
        RagCitation(
            urn="urn:li:dataset:(urn:li:dataPlatform:dbt,db.orders,PROD)",
            label="orders",
            entity_type="DATASET",
            platform_urn="urn:li:dataPlatform:dbt",
            source="datahub_mcp_live",
        ),
        RagCitation(
            urn="urn:li:schemaField:(urn:li:dataset:orders,ORDERS_COUNT)",
            label="ORDERS_COUNT",
            entity_type="SCHEMAFIELD",
            platform_urn="urn:li:dataPlatform:tableau",
            source="datahub_mcp_live",
        ),
    ]

    filtered = _filter_general_matches(
        "Tell me about the Snowflake orders dataset", "orders", matches
    )

    assert [item.urn for item in filtered] == [matches[0].urn]


@pytest.mark.asyncio
async def test_structured_schema_answer_is_rendered_without_model_paraphrase() -> None:
    completion = AnyCompletion()
    response = await HybridChatAgent(
        SchemaDataHub(), SchemaIndex(), completion=completion, planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Show the schema and columns of orders"))

    assert response.answer.startswith("- DataHub schema lookup for shop.orders")
    assert "column=order_id" in response.answer
    assert response.verification and response.verification.passed
    assert response.verification.claim_coverage == 1.0


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


@pytest.mark.asyncio
async def test_agent_never_reads_schema_for_an_unverified_qdrant_candidate() -> None:
    datahub = NoMatchDataHub()
    response = await HybridChatAgent(
        datahub, SchemaIndex(), completion=SafeNoMatchCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Show the schema of a nonexistent asset"))

    assert datahub.schema_calls == []
    assert response.verification and not response.verification.passed
    assert response.target_resolution and response.target_resolution.status == "NOT_FOUND"


@pytest.mark.asyncio
async def test_qdrant_semantic_candidate_guides_an_exact_live_mcp_confirmation() -> None:
    datahub = GuidedAliasDataHub()
    response = await HybridChatAgent(
        datahub,
        GuidedAliasIndex(datahub.urn),
        completion=AnyCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Show the schema for the revenue semantic asset"))

    assert datahub.search_queries == ["revenue", "shop.orders"]
    assert datahub.schema_calls == [datahub.urn]
    assert response.target_resolution and response.target_resolution.status == "RESOLVED"
    assert response.target_resolution.targets[0].source == "datahub_mcp_live_qdrant_guided"
    assert response.verification and response.verification.passed


@pytest.mark.asyncio
async def test_stale_qdrant_candidate_cannot_authorize_a_schema_read() -> None:
    datahub = GuidedAliasDataHub(confirm_exact=False)
    response = await HybridChatAgent(
        datahub,
        GuidedAliasIndex(datahub.urn),
        completion=SafeNoMatchCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Show the schema for the revenue semantic asset"))

    assert datahub.search_queries == ["revenue", "shop.orders"]
    assert datahub.schema_calls == []
    assert response.target_resolution and response.target_resolution.status == "NOT_FOUND"
    assert response.active_verified_asset is None


@pytest.mark.asyncio
async def test_qdrant_guidance_is_bounded_even_with_many_vector_hits() -> None:
    datahub = BoundedConfirmationDataHub()
    response = await HybridChatAgent(
        datahub,
        ManyCandidatesIndex(),
        completion=SafeNoMatchCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Show the schema for the revenue semantic asset"))

    assert datahub.batch_size == 3
    assert response.target_resolution and response.target_resolution.status == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_schema_field_hits_confirm_their_exact_parent_dataset_once() -> None:
    datahub = SchemaFieldParentDataHub()
    response = await HybridChatAgent(
        datahub,
        SchemaFieldParentIndex(),
        completion=AnyCompletion(),
        planner=KeywordPlanningProvider(),
    ).respond(ChatRequest(message="Show the schema for the commerce fact"))

    assert datahub.search_queries == ["commerce", "db.sales.orders"]
    assert datahub.schema_calls == [SchemaFieldParentIndex.parent]
    assert response.target_resolution and response.target_resolution.status == "RESOLVED"
    assert response.verification and response.verification.passed


class AmbiguousOrdersDataHub:
    def __init__(self) -> None:
        self.schema_calls: list[str] = []
        self.lineage_calls: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        assert query == "orders"
        return {"structuredContent": {"searchResults": [
            {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.orders,PROD)", "type": "DATASET", "properties": {"name": "orders"}, "platform": {"urn": "urn:li:dataPlatform:snowflake"}}},
            {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders,PROD)", "type": "DATASET", "properties": {"name": "orders"}, "platform": {"urn": "urn:li:dataPlatform:dbt"}}},
        ]}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": []}}

    async def get_lineage(self, urn: str, direction: str, max_hops: int, max_results: int = 100) -> dict:
        self.lineage_calls.append(urn)
        return {"structuredContent": {"downstreams": {"searchResults": []}}}


@pytest.mark.asyncio
async def test_schema_or_lineage_never_selects_an_ambiguous_orders_asset() -> None:
    datahub = AmbiguousOrdersDataHub()
    response = await HybridChatAgent(
        datahub, SchemaIndex(), completion=SafeNoMatchCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="Show the downstream lineage of the orders dataset"))

    assert response.target_resolution and response.target_resolution.status == "AMBIGUOUS"
    assert datahub.schema_calls == []
    assert datahub.lineage_calls == []
    assert response.verification and not response.verification.passed


class SnowflakeOrdersDataHub:
    snowflake_orders = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.orders,PROD)"
    order_details = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.order_details,PROD)"

    def __init__(self) -> None:
        self.schema_calls: list[str] = []

    async def search(self, query: str, num_results: int = 10, offset: int = 0) -> dict:
        assert query == "orders"
        return {"structuredContent": {"searchResults": [
            {"entity": {"urn": self.snowflake_orders, "type": "DATASET", "properties": {"name": "orders"}, "platform": {"urn": "urn:li:dataPlatform:snowflake"}}},
            {"entity": {"urn": self.order_details, "type": "DATASET", "properties": {"name": "order_details"}, "platform": {"urn": "urn:li:dataPlatform:snowflake"}}},
        ]}}

    async def list_schema_fields(self, urn: str) -> dict:
        self.schema_calls.append(urn)
        return {"structuredContent": {"fields": [{"fieldPath": "order_id", "nativeDataType": "NUMBER"}]}}


@pytest.mark.asyncio
async def test_snowflake_orders_schema_is_locked_to_the_exact_resolved_urn() -> None:
    datahub = SnowflakeOrdersDataHub()
    response = await HybridChatAgent(
        datahub, SchemaIndex(), completion=AnyCompletion(), planner=KeywordPlanningProvider()  # type: ignore[arg-type]
    ).respond(ChatRequest(message="What is the schema of the Snowflake orders dataset?"))

    assert response.target_resolution and response.target_resolution.status == "RESOLVED"
    assert [item.urn for item in response.target_resolution.targets] == [datahub.snowflake_orders]
    assert datahub.schema_calls == [datahub.snowflake_orders]
    assert all(datahub.order_details not in evidence.asset_urn for evidence in response.evidence)
    assert response.verification and response.verification.passed


def test_claim_verifier_checks_every_sentence_not_only_citation_presence() -> None:
    evidence = [
        AgentEvidence(
            id="E-schema-orders",
            kind="schema",
            asset_urn=SnowflakeOrdersDataHub.snowflake_orders,
            summary="DataHub schema lookup for orders returned 1 field.",
            facts=["column=order_id, type=NUMBER"],
        )
    ]

    claims = _verify_factual_claims(
        "order_id has type NUMBER [E-schema-orders]. customer_secret has type TEXT [E-schema-orders].",
        evidence,
        {SnowflakeOrdersDataHub.snowflake_orders},
    )

    assert [claim.supported for claim in claims] == [True, False]
    assert "customer_secret" in claims[1].reason


def test_claim_verifier_rejects_unknown_and_wrong_target_evidence() -> None:
    evidence = [
        AgentEvidence(
            id="E-schema-details",
            kind="schema",
            asset_urn=SnowflakeOrdersDataHub.order_details,
            summary="Schema for order_details.",
            facts=["column=order_id, type=NUMBER"],
        )
    ]

    unknown = _verify_factual_claims(
        "order_id has type NUMBER. [E-does-not-exist]",
        evidence,
        {SnowflakeOrdersDataHub.snowflake_orders},
    )
    wrong_target = _verify_factual_claims(
        "order_id has type NUMBER. [E-schema-details]",
        evidence,
        {SnowflakeOrdersDataHub.snowflake_orders},
    )

    assert not unknown[0].supported
    assert "Unknown evidence IDs" in unknown[0].reason
    assert not wrong_target[0].supported
    assert "different asset" in wrong_target[0].reason


def test_claim_verifier_rejects_invented_counts_and_unsupported_absence() -> None:
    evidence = [
        AgentEvidence(
            id="E-lineage-orders",
            kind="lineage",
            asset_urn=SnowflakeOrdersDataHub.snowflake_orders,
            summary="DataHub downstream lineage for orders returned 1 direct relationship.",
            facts=["downstream=urn:li:dataset:dashboard_orders, hops=1"],
        )
    ]

    claims = _verify_factual_claims(
        "orders has 36 downstream assets [E-lineage-orders]. orders has no owner [E-lineage-orders].",
        evidence,
        {SnowflakeOrdersDataHub.snowflake_orders},
    )

    assert [claim.supported for claim in claims] == [False, False]
    assert "36" in claims[0].reason
    assert "absence claim" in claims[1].reason.lower()


def test_claim_verifier_rejects_an_invented_ordinary_language_property() -> None:
    evidence = [
        AgentEvidence(
            id="E1",
            kind="search",
            asset_urn=SnowflakeOrdersDataHub.snowflake_orders,
            summary="DataHub search matched orders (DATASET).",
            facts=["asset=orders", "entity_type=DATASET"],
        )
    ]

    claim = _verify_factual_claims(
        "orders is business-critical. [E1]", evidence, set()
    )[0]

    assert not claim.supported
    assert "business-critical" in claim.reason


def test_claim_verifier_accepts_catalog_presence_wording() -> None:
    evidence = [
        AgentEvidence(
            id="E1",
            kind="search",
            asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
            summary="ORDERS (DATASET)",
            facts=["label=ORDERS", "platform=urn:li:dataPlatform:snowflake"],
        ),
        AgentEvidence(
            id="E2",
            kind="search",
            asset_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,orders,PROD)",
            summary="orders (DATASET)",
            facts=["label=orders", "platform=urn:li:dataPlatform:postgres"],
        ),
    ]

    claims = _verify_factual_claims(
        "There are two orders datasets [E1] [E2].\n"
        "It is available on Snowflake [E1].",
        evidence,
        set(),
    )

    assert claims
    assert all(claim.supported for claim in claims)
