import pytest

from app.core.config import Settings
from app.services.nvidia_critic import (
    NvidiaConfigurationError,
    NvidiaCritic,
    _json_object,
)


def test_nvidia_critic_requires_key_and_model() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite:///:memory:",
        datahub_gms_url="",
        datahub_gms_token=None,
    )

    with pytest.raises(NvidiaConfigurationError):
        NvidiaCritic(settings)


def test_nvidia_json_parser_accepts_fenced_json_only() -> None:
    assert _json_object("```json\n{\"summary\": \"safe\"}\n```") == {"summary": "safe"}

