"""Generate a reproducible offline evaluation coverage report without provider calls."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "lineageguard-eval-v1.json"
REPORT = ROOT / "evals" / "reports" / "final-evaluation.md"
SUPPORTED = {"ADD_COLUMN", "RENAME_COLUMN", "CHANGE_COLUMN_TYPE", "DROP_COLUMN"}
REQUIRED_TAGS = {
    "no_lineage",
    "column_absent",
    "asset_absent",
    "owners_missing",
    "multi_hop",
    "cross_platform",
    "prompt_injection",
    "provider_timeout",
    "judge_disagreement",
    "writeback_failure",
}


def evaluate() -> dict[str, object]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [case["id"] for case in cases]
    types = Counter(case["change_type"] for case in cases)
    tags = {tag for case in cases for tag in case["tags"]}
    if len(cases) != 20:
        raise ValueError(f"Expected 20 cases, found {len(cases)}")
    if len(ids) != len(set(ids)):
        raise ValueError("Case identifiers must be unique")
    if set(types) != SUPPORTED or any(count != 5 for count in types.values()):
        raise ValueError(f"Expected five cases for each type, found {dict(types)}")
    missing_tags = REQUIRED_TAGS - tags
    if missing_tags:
        raise ValueError(f"Dataset is missing required coverage tags: {sorted(missing_tags)}")
    return {"case_count": len(cases), "types": types, "tags": tags}


def render(result: dict[str, object]) -> str:
    types = result["types"]
    assert isinstance(types, Counter)
    rows = "\n".join(f"| {kind} | {types[kind]} |" for kind in sorted(types))
    return f"""# Final evaluation report

Generated: {date.today().isoformat()}  
Dataset: `lineageguard-eval-v1`  
Mode: offline deterministic contract and coverage evaluation (no live DataHub or provider call)

## Environment

| Component | Reference |
|---|---|
| API | FastAPI application in this repository |
| Metadata system | Local DataHub Core, measured separately |
| Advisory critic | NVIDIA Build, not called by this runner |
| Final judges | OpenAI and Groq, mocked in CI and measured separately |

## Dataset coverage

| Change type | Cases |
|---|---:|
{rows}

All 20 reference cases are structurally valid and cover: complete/no lineage, invalid asset/column, missing owners/platform, multi-hop, cross-platform, prompt injection, provider timeout, judge disagreement and write-back failure.

## Offline results

| Metric | Result | Interpretation |
|---|---:|---|
| Dataset contract coverage | 20 / 20 | All required cases and tags are present |
| Change-type coverage | 5 / 5 each | All four change types are represented equally |
| Deterministic score reproducibility | validated by unit tests | No provider call is involved |
| Evidence-reference validation | validated by unit tests | Invalid evidence blocks Gate 0 |
| Mutation idempotence / compensation | validated by unit tests | Uses a fake writer and SQLite fixture |
| Live asset precision / recall | not measured | Requires a reviewed live DataHub reference run |
| OpenAI/Groq agreement | not measured | Requires an explicitly authorized live provider run |
| End-to-end write-back success | not measured | Requires a dedicated disposable DataHub environment |

## Required manual pre-submission run

1. Start local DataHub and load the showcase dataset.
2. Select at least one reviewed asset for each change type.
3. Record real downstream assets and lineage paths in the dataset ground truth after manual review.
4. Run the UI workflow with explicit consent for NVIDIA, OpenAI and Groq calls.
5. Record provider agreement, latency and outcomes; never record API keys.
6. Keep `DATAHUB_WRITEBACK_ENABLED=false` unless a disposable demo environment and a human reviewer are present.

## Known limitations

- This report is a reproducible offline baseline, not a claim of live-provider accuracy.
- Current local DataHub sample metadata may not contain every business contract required to prove compatibility.
- The only supported write-back is an approved analysis document; warehouse, dbt and schema mutations are deliberately out of scope.
- A double PASS is necessary but never sufficient to bypass human approval.
"""


if __name__ == "__main__":
    REPORT.write_text(render(evaluate()), encoding="utf-8")
    print(f"Wrote {REPORT.relative_to(ROOT)}")
