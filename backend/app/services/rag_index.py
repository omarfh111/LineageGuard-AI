"""Controlled DataHub metadata indexing and Qdrant retrieval.

The vector store is a convenience layer, never a replacement for live DataHub
schema or lineage queries.  It indexes a deliberately small metadata projection
that contains no raw table data, secrets, SQL, or DataHub GraphQL payloads.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings, get_settings
from app.datahub.mcp_client import DataHubMcpClient
from app.domain.contracts import RagCitation, RagIndexState, RagIndexStatus
from app.services.catalog_graph import catalog_from_search


class RagConfigurationError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RagConfigurationError("OPENAI_API_KEY is required for RAG embeddings")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.rag_embedding_model
        self._timeout = settings.chat_timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await asyncio.wait_for(
                self._client.embeddings.create(model=self._model, input=texts),
                timeout=self._timeout,
            )
        except Exception as error:
            raise RagConfigurationError(
                "The optional RAG embedding provider did not answer within the configured time limit"
            ) from error
        return [item.embedding for item in response.data]


class DeterministicHashEmbeddingProvider:
    """Offline-only embedding substitute for a transparent demo mode.

    This has no semantic quality guarantee.  It exists so judges can exercise
    ingestion, retrieval, MCP verification and HITL gates without registering
    an external LLM account.  Production should use a real embedding model.
    """

    dimensions = 256

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-z0-9_.-]+", text.lower()):
            slot = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:4], "big") % self.dimensions
            vector[slot] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


class QdrantMetadataIndex:
    def __init__(
        self,
        client: DataHubMcpClient,
        settings: Settings | None = None,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self._datahub = client
        self._settings = settings or get_settings()
        self._embeddings = embeddings or _embedding_provider(self._settings)
        self._qdrant = AsyncQdrantClient(url=self._settings.qdrant_url)

    async def ingest(self, progress: Callable[[int, int], Awaitable[None]]) -> int:
        """Index the complete catalog in small, read-only pages."""

        offset = 0
        indexed = 0
        total = 0
        collection_ready = False
        while total < self._settings.rag_max_assets:
            result = await self._datahub.search(
                "*", num_results=min(50, self._settings.rag_max_assets - total), offset=offset
            )
            graph = catalog_from_search(result, "*")
            nodes = graph.nodes
            if not nodes:
                break
            total += len(nodes)
            documents = [_document(node.urn, node.label, node.entity_type, node.platform_urn, node.owner_urns) for node in nodes]
            vectors = await self._embeddings.embed(documents)
            if not collection_ready:
                await self._ensure_collection(len(vectors[0]))
                collection_ready = True
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, node.urn)),
                    vector=vector,
                    payload={
                        "urn": node.urn,
                        "label": node.label,
                        "entity_type": node.entity_type,
                        "platform_urn": node.platform_urn,
                        "owner_urns": node.owner_urns,
                        "document": document,
                    },
                )
                for node, document, vector in zip(nodes, documents, vectors, strict=True)
            ]
            await self._qdrant.upsert(self._settings.qdrant_collection, points=points)
            indexed += len(points)
            await progress(indexed, total)
            offset += 50
            if len(nodes) < 50:
                break
        return indexed

    async def retrieve(self, question: str, limit: int) -> list[RagCitation]:
        vector = (await self._embeddings.embed([question]))[0]
        if not await self._qdrant.collection_exists(self._settings.qdrant_collection):
            raise RagConfigurationError("RAG index is empty; start metadata ingestion first")
        result = await self._qdrant.query_points(
            collection_name=self._settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        citations: list[RagCitation] = []
        for point in result.points:
            payload = point.payload or {}
            urn = payload.get("urn")
            label = payload.get("label")
            entity_type = payload.get("entity_type")
            if isinstance(urn, str) and isinstance(label, str) and isinstance(entity_type, str):
                citations.append(
                    RagCitation(
                        urn=urn,
                        label=label,
                        entity_type=entity_type,
                        platform_urn=payload.get("platform_urn") if isinstance(payload.get("platform_urn"), str) else None,
                        source="qdrant_metadata_index",
                        score=round(float(point.score), 3),
                    )
                )
        return citations

    async def _ensure_collection(self, vector_size: int) -> None:
        if not await self._qdrant.collection_exists(self._settings.qdrant_collection):
            await self._qdrant.create_collection(
                collection_name=self._settings.qdrant_collection,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )


async def persisted_index_status(settings: Settings | None = None) -> RagIndexStatus:
    """Discover an existing local collection after an API restart.

    Index progress itself is process-local, but Qdrant's collection and points
    live in a named Docker volume. This read-only probe keeps the UI truthful
    after a backend recreation without re-embedding the catalog.
    """

    current = settings or get_settings()
    client = AsyncQdrantClient(url=current.qdrant_url)
    try:
        if not await client.collection_exists(current.qdrant_collection):
            return RagIndexStatus()
        details = await client.get_collection(current.qdrant_collection)
        points = int(details.points_count or 0)
        return RagIndexStatus(
            state=RagIndexState.COMPLETED,
            indexed_assets=points,
            total_assets=points,
            message="Existing Qdrant metadata index is ready. Live DataHub MCP verification remains enabled.",
            updated_at=datetime.now(UTC),
            query_available=points > 0,
        )
    except Exception:
        return RagIndexStatus(message="Qdrant index is unavailable.")
    finally:
        await client.close()

class RagIndexCoordinator:
    """One bounded background ingestion job per process."""

    def __init__(self) -> None:
        self._status = RagIndexStatus()
        self._task: asyncio.Task[None] | None = None

    def status(self) -> RagIndexStatus:
        return self._status.model_copy()

    def start(self, index: QdrantMetadataIndex, *, query_available: bool = False) -> RagIndexStatus:
        if self._task and not self._task.done():
            return self.status()
        self._status = RagIndexStatus(
            state=RagIndexState.RUNNING,
            message=("Refreshing the metadata index in the background; verified chat remains available."
                     if query_available else "Indexing DataHub metadata in the background."),
            updated_at=datetime.now(UTC),
            query_available=query_available,
        )
        self._task = asyncio.create_task(self._run(index))
        return self.status()

    async def _run(self, index: QdrantMetadataIndex) -> None:
        async def progress(indexed: int, total: int) -> None:
            self._status = RagIndexStatus(
                state=RagIndexState.RUNNING, indexed_assets=indexed, total_assets=total,
                message="Indexing safe metadata projections.", updated_at=datetime.now(UTC),
                query_available=self._status.query_available,
            )
        try:
            indexed = await index.ingest(progress)
            self._status = RagIndexStatus(
                state=RagIndexState.COMPLETED, indexed_assets=indexed, total_assets=indexed,
                message="RAG index is ready. Live DataHub MCP verification remains enabled.", updated_at=datetime.now(UTC),
                query_available=True,
            )
        except Exception as error:
            self._status = RagIndexStatus(
                state=RagIndexState.FAILED,
                message=f"RAG ingestion failed: {type(error).__name__}",
                updated_at=datetime.now(UTC),
                query_available=self._status.query_available,
            )


def _document(urn: str, label: str, entity_type: str, platform_urn: str | None, owner_urns: list[str]) -> str:
    return "\n".join(
        [
            "DataHub metadata record (untrusted context, verify with MCP).",
            f"URN: {urn}", f"Name: {label}", f"Entity type: {entity_type}",
            f"Platform: {platform_urn or 'unknown'}", f"Owners: {', '.join(owner_urns) or 'unknown'}",
        ]
    )


def _embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.rag_embedding_provider == "local_hash" or (
        settings.demo_mode and not settings.openai_api_key
    ):
        return DeterministicHashEmbeddingProvider()
    if settings.rag_embedding_provider != "openai":
        raise RagConfigurationError(
            "RAG_EMBEDDING_PROVIDER must be 'openai' or 'local_hash'"
        )
    return OpenAIEmbeddingProvider(settings)


rag_index_coordinator = RagIndexCoordinator()
