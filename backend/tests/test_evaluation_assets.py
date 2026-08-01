import importlib.util
import json
from pathlib import Path


def _runner_module():
    path = Path(__file__).parents[2] / "evals" / "runners" / "run_deterministic_evals.py"
    spec = importlib.util.spec_from_file_location("lineageguard_eval_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_dataset_has_required_phase_seven_coverage() -> None:
    result = _runner_module().evaluate()

    assert result["case_count"] == 20
    assert set(result["types"].values()) == {5}
    assert "prompt_injection" in result["tags"]
    assert "writeback_failure" in result["tags"]


def test_professional_rag_dataset_has_reviewed_live_acceptance_coverage() -> None:
    root = Path(__file__).parents[2]
    dataset_path = root / "evals" / "datasets" / "professional-agentic-rag-v1.json"
    runner_path = root / "evals" / "runners" / "run_live_agentic_evals.py"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("live_agentic_eval_runner", runner_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = module.load_cases(payload)

    assert payload["dataset_type"] == "rag"
    assert payload["reviewed_at"]
    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(bool(case["expected"].get("relevant_urns")) for case in cases) >= 20
    assert all(case["expected"].get("tools") for case in cases)
    assert all("verification_passed" in case["expected"] for case in cases)
    assert all("target_status" in case["expected"] for case in cases)
