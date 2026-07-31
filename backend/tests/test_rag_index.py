from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.rag_index import (
    DeterministicHashEmbeddingProvider,
    QdrantMetadataIndex,
    RagConfigurationError,
    _active_alias,
)


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite://",
        datahub_gms_url="http://datahub",
        datahub_gms_token=None,
        qdrant_url="http://qdrant",
        qdrant_collection="rag_test",
        rag_embedding_provider="local_hash",
        rag_max_assets=10,
    )


def entity(name: str) -> dict:
    return {
        "entity": {
            "urn": f"urn:li:dataset:(urn:li:dataPlatform:snowflake,db.{name},PROD)",
            "type": "DATASET",
            "properties": {"name": name},
            "platform": {"urn": "urn:li:dataPlatform:snowflake"},
        }
    }


class MutableDataHub:
    def __init__(self, names: list[str]) -> None:
        self.names = names

    async def search(self, query: str, num_results: int, offset: int = 0) -> dict:
        rows = [entity(name) for name in self.names[offset : offset + num_results]]
        return {"structuredContent": {"searchResults": rows}}


class FakeQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, object]] = {}
        self.aliases: dict[str, str] = {}

    async def get_aliases(self):
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    async def collection_exists(self, name: str) -> bool:
        return name in self.collections

    async def create_collection(self, collection_name: str, vectors_config: object) -> None:
        assert collection_name not in self.collections
        self.collections[collection_name] = {}

    async def upsert(self, collection_name: str, points: list, wait: bool = True) -> None:
        assert wait
        for point in points:
            self.collections[collection_name][str(point.id)] = point

    async def get_collection(self, name: str):
        physical = self.aliases.get(name, name)
        return SimpleNamespace(points_count=len(self.collections[physical]))

    async def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.collections]
        )

    async def update_collection_aliases(self, operations: list) -> bool:
        updated = dict(self.aliases)
        for operation in operations:
            delete_alias = getattr(operation, "delete_alias", None)
            create_alias = getattr(operation, "create_alias", None)
            if delete_alias is not None:
                updated.pop(delete_alias.alias_name, None)
            if create_alias is not None:
                updated[create_alias.alias_name] = create_alias.collection_name
        self.aliases = updated
        return True

    async def delete_collection(self, name: str) -> bool:
        self.collections.pop(name, None)
        return True

    async def query_points(self, collection_name: str, **_: object):
        physical = self.aliases.get(collection_name, collection_name)
        points = [
            SimpleNamespace(payload=point.payload, score=1.0)
            for point in self.collections[physical].values()
        ]
        return SimpleNamespace(points=points)


async def no_progress(_: int, __: int) -> None:
    return None


@pytest.mark.asyncio
async def test_reindex_atomically_removes_stale_qdrant_records() -> None:
    datahub = MutableDataHub(["orders", "obsolete_orders"])
    qdrant = FakeQdrant()
    index = QdrantMetadataIndex(datahub, settings(), DeterministicHashEmbeddingProvider())  # type: ignore[arg-type]
    index._qdrant = qdrant  # type: ignore[assignment]

    assert await index.ingest(no_progress) == 2
    first_snapshot = qdrant.aliases[_active_alias("rag_test")]
    datahub.names = ["orders"]
    assert await index.ingest(no_progress) == 1

    second_snapshot = qdrant.aliases[_active_alias("rag_test")]
    assert second_snapshot != first_snapshot
    assert first_snapshot not in qdrant.collections
    assert len(qdrant.collections[second_snapshot]) == 1
    citations = await index.retrieve("orders", 10)
    assert [citation.label for citation in citations] == ["orders"]


@pytest.mark.asyncio
async def test_failed_empty_rebuild_preserves_previous_active_snapshot() -> None:
    datahub = MutableDataHub(["orders"])
    qdrant = FakeQdrant()
    index = QdrantMetadataIndex(datahub, settings(), DeterministicHashEmbeddingProvider())  # type: ignore[arg-type]
    index._qdrant = qdrant  # type: ignore[assignment]
    await index.ingest(no_progress)
    active_before = qdrant.aliases[_active_alias("rag_test")]
    datahub.names = []

    with pytest.raises(RagConfigurationError, match="existing index was preserved"):
        await index.ingest(no_progress)

    assert qdrant.aliases[_active_alias("rag_test")] == active_before
    assert active_before in qdrant.collections
    assert not any("__snapshot__" in name and name != active_before for name in qdrant.collections)
