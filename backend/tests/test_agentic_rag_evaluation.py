import importlib.util
from pathlib import Path


def test_agentic_rag_fixture_metrics_enforce_grounding_gates() -> None:
    path = Path(__file__).parents[2] / "evals" / "runners" / "run_agentic_rag_evals.py"
    spec = importlib.util.spec_from_file_location("lineageguard_agentic_rag_evals", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    metrics = module.evaluate()

    assert metrics["case_count"] == 5
    assert metrics["asset_precision"] == 1.0
    assert metrics["asset_recall"] == 1.0
    assert metrics["schema_exact_match"] == 1.0
    assert metrics["tool_selection_accuracy"] == 1.0
    assert metrics["verification_block_rate"] == 1.0
    assert metrics["citation_coverage_verified_answers"] == 1.0
    assert metrics["unsupported_claim_rate_before_guard"] == 0.4
    assert metrics["post_verification_unsupported_claim_rate"] == 0.0
