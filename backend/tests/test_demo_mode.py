import pytest

from app.core.config import Settings
from app.services.rag_index import DeterministicHashEmbeddingProvider, _embedding_provider


@pytest.mark.asyncio
async def test_local_hash_embeddings_are_deterministic_and_no_key() -> None:
    provider = DeterministicHashEmbeddingProvider()

    first = await provider.embed(["orders customer_id"])
    second = await provider.embed(["orders customer_id"])

    assert first == second
    assert len(first[0]) == 256


def test_demo_mode_selects_local_embeddings_without_openai_key() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite:///:memory:",
        datahub_gms_url="http://localhost:8080",
        datahub_gms_token=None,
        openai_api_key=None,
        demo_mode=True,
    )

    assert isinstance(_embedding_provider(settings), DeterministicHashEmbeddingProvider)
