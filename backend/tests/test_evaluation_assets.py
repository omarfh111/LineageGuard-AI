import importlib.util
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
