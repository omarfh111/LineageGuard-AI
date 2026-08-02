from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.contracts import AdvisoryCritique, CritiqueRequest
from app.services.nvidia_critic import (
    NvidiaConfigurationError,
    NvidiaCritic,
    _json_object,
    _normalize_critique_payload,
    _validation_signature,
)
from test_judging import judging_request


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


def test_nvidia_payload_normalizes_glm_nested_shape_and_filters_evidence() -> None:
    normalized = _normalize_critique_payload({
        "critique": {
            "overall_assessment": "Review required.",
            "issues": {
                "high": [{
                    "title": "Schema concern",
                    "references": ["ev_schema_source", "invented-id"],
                }],
            },
            "revisions": {"first": "Recheck the schema."},
            "confidence": {"score": "4/5"},
        },
    }, allowed_evidence_ids={"ev_schema_source"})

    assert normalized["summary"] == "Review required."
    assert normalized["issues"] == [{
        "severity": "CRITICAL",
        "finding": "Schema concern",
        "evidence_ids": ["ev_schema_source"],
    }]
    assert normalized["recommended_revisions"] == ["Recheck the schema."]
    assert normalized["confidence"] == 0.8


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


@pytest.mark.asyncio
async def test_nvidia_critic_repairs_once_inside_exact_contract() -> None:
    first = (
        '{"summary":"Review required.","issues":[],"recommended_revisions":[],'
        '"confidence":"high"}'
    )
    second = (
        '{"summary":"Review required.","issues":[],"recommended_revisions":[],'
        '"confidence":0.8}'
    )
    completions = _FakeCompletions([first, second])
    critic = object.__new__(NvidiaCritic)
    critic._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    critic._model = "z-ai/glm-5.2"
    critic._timeout = 5
    request = judging_request()

    result = await critic.critique(CritiqueRequest(
        impact_report=request.impact_report,
        remediation_plan=request.remediation_plan,
    ))

    assert result.confidence == 0.8
    assert len(completions.calls) == 2
    assert completions.calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert completions.calls[0]["stream"] is True
    assert "risk_assessment" not in str(completions.calls[1]["messages"])


def test_nvidia_validation_signature_never_contains_provider_values() -> None:
    with pytest.raises(ValidationError) as captured:
        AdvisoryCritique.model_validate({
            "provider": "nvidia",
            "model": "model",
            "summary": "safe",
            "issues": [{"severity": "MAJOR", "finding": None}],
            "recommended_revisions": [],
            "confidence": 2,
        })

    signature = _validation_signature(captured.value)
    assert "issues.0.finding:string_type" in signature
    assert "confidence:less_than_equal" in signature
    assert "safe" not in signature
