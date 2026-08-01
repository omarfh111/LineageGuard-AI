from pathlib import Path

from app.services.run_store import AnalysisStore, RunStore
from test_judging import judging_request, verdict
from app.domain.contracts import (
    AggregateDecision,
    DeterministicValidation,
    JudgeAggregation,
    JudgeProvider,
    JudgeStatus,
    JudgingResult,
)


def test_judging_run_survives_store_recreation() -> None:
    database_path = Path(__file__).with_name(".run-store-test.db")
    database_path.unlink(missing_ok=True)
    database_url = f"sqlite:///{database_path}"
    result = JudgingResult(
        deterministic_validation=DeterministicValidation(passed=True, errors=[]),
        openai_verdict=verdict(JudgeProvider.OPENAI, JudgeStatus.PASS),
        groq_verdict=verdict(JudgeProvider.GROQ, JudgeStatus.PASS),
        aggregate_decision=JudgeAggregation(
            decision=AggregateDecision.FINALIZE_READ_ONLY,
            human_review_required=False,
            rationale="test",
        ),
    )
    run_id = RunStore(database_url).save(judging_request(), result)

    stored = RunStore(database_url).get(run_id)
    assert stored is not None
    assert stored[1].aggregate_decision.decision == "FINALIZE_READ_ONLY"
    history = RunStore(database_url).list_recent()
    assert history[0].run_id == run_id
    assert history[0].openai_status == "PASS"
    database_path.unlink()


def test_analysis_snapshot_is_server_owned_and_survives_store_recreation() -> None:
    database_path = Path(__file__).with_name(".analysis-store-test.db")
    database_path.unlink(missing_ok=True)
    try:
        database_url = f"sqlite:///{database_path}"
        request = judging_request()
        run_id = AnalysisStore(database_url).save(
            request.impact_report, request.remediation_plan
        )

        request.impact_report.risk_assessment.score = 0
        restored = AnalysisStore(database_url).get(run_id)

        restored_snapshot = AnalysisStore(database_url).restore(run_id)

        assert restored is not None
        assert restored_snapshot is not None
        assert restored.impact_report.risk_assessment.score == 45
        assert restored_snapshot[0].risk_assessment.score == 45
        assert (
            restored.remediation_plan.source_asset_urn
            == request.impact_report.request.asset_urn
        )
    finally:
        database_path.unlink(missing_ok=True)


def test_unknown_analysis_snapshot_cannot_be_restored() -> None:
    database_path = Path(__file__).with_name(".analysis-store-missing-test.db")
    database_path.unlink(missing_ok=True)
    try:
        assert AnalysisStore(f"sqlite:///{database_path}").restore("missing") is None
    finally:
        database_path.unlink(missing_ok=True)
