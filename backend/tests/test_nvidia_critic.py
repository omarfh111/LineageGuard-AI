import pytest

from app.core.config import Settings
from app.services.nvidia_critic import (
    NvidiaConfigurationError,
    NvidiaCritic,
    _json_object,
    _normalize_critique_payload,
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


def test_nvidia_json_parser_accepts_one_embedded_complete_object() -> None:
    assert _json_object(
        '<think>bounded review complete</think>\n{"summary":"safe","confidence":0.9}'
    ) == {"summary": "safe", "confidence": 0.9}


def test_nvidia_json_parser_does_not_invent_malformed_json() -> None:
    with pytest.raises(ValueError):
        _json_object("Result: {summary: safe}")


def test_nvidia_payload_normalizes_conservative_provider_variants() -> None:
    assert _normalize_critique_payload({
        "assessment": "Review required.",
        "issues": [{"severity": "HIGH", "description": "Check E-1", "evidence_ids": "E-1"}],
        "recommendations": [{"action": "Recheck the contract."}],
        "confidence": "85%",
    }) == {
        "assessment": "Review required.",
        "summary": "Review required.",
        "issues": [{"severity": "CRITICAL", "finding": "Check E-1", "evidence_ids": ["E-1"]}],
        "recommendations": [{"action": "Recheck the contract."}],
        "recommended_revisions": ["Recheck the contract."],
        "confidence": 0.85,
    }


def test_nvidia_payload_keeps_missing_finding_invalid() -> None:
    normalized = _normalize_critique_payload({
        "summary": "Review required.",
        "issues": [{"severity": "LOW"}],
        "recommended_revisions": [],
        "confidence": 0.5,
    })
    assert normalized["issues"] == [{"severity": "MAJOR", "finding": None, "evidence_ids": []}]
