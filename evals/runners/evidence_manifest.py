"""Create immutable, versioned evaluation evidence without collecting secrets."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_SCHEMA_VERSION = "1.0.0"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_files(dataset_path: Path) -> list[Path]:
    paths = list((ROOT / "backend" / "app").rglob("*.py"))
    paths.extend(
        ROOT / "frontend" / "src" / name
        for name in ("App.tsx", "analysisFlow.ts", "recovery.ts")
    )
    paths.extend((ROOT / "evals" / "runners").glob("*.py"))
    paths.append(dataset_path.resolve())
    return sorted({path.resolve() for path in paths if path.is_file()})


def source_digest(dataset_path: Path) -> tuple[str, list[str]]:
    digest = hashlib.sha256()
    files: list[str] = []
    for path in _source_files(dataset_path):
        relative = path.relative_to(ROOT).as_posix()
        files.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), files


def build_manifest(
    dataset_path: Path,
    evaluator: str,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    source_sha, source_files = source_digest(dataset_path)
    patch = _git("diff", "--no-ext-diff", "--binary", "HEAD", "--") or ""
    status = _git("status", "--porcelain", "--untracked-files=no") or ""
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluator": evaluator,
        "dataset": {
            "id": dataset.get("dataset_id", dataset_path.stem),
            "version": dataset.get("dataset_version", "unversioned"),
            "path": dataset_path.resolve().relative_to(ROOT).as_posix(),
            "sha256": sha256_file(dataset_path),
        },
        "source": {
            "sha256": source_sha,
            "files": source_files,
            "git_revision": _git("rev-parse", "HEAD"),
            "git_dirty": bool(status),
            "tracked_patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        },
        "runtime": runtime or {},
    }


def write_evidence(
    result: dict[str, Any],
    dataset_path: Path,
    evaluator: str,
    output_dir: Path,
    runtime: dict[str, Any] | None = None,
) -> Path:
    manifest = build_manifest(dataset_path, evaluator, runtime)
    dataset_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", manifest["dataset"]["id"])
    version = re.sub(r"[^a-zA-Z0-9_.-]+", "-", manifest["dataset"]["version"])
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{dataset_id}-{version}-{evaluator}-{timestamp}-{manifest['source']['sha256'][:12]}.json"
    target = (ROOT / output_dir).resolve() if not output_dir.is_absolute() else output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    evidence_path = target / filename
    envelope = {"evidence_manifest": manifest, "results": result}
    with evidence_path.open("x", encoding="utf-8") as stream:
        json.dump(envelope, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return evidence_path
