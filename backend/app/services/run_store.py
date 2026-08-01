"""Persistent, server-owned judge runs used to authorize HITL preparation."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.domain.contracts import (
    ImpactReport,
    JudgingRequest,
    JudgingResult,
    JudgingRunSummary,
    RemediationPlan,
)


def sqlite_path(database_url: str) -> str:
    """Resolve the SQLite subset supported by the MVP without leaking credentials."""

    if database_url == "sqlite:///:memory:":
        return ":memory:"
    if database_url.startswith("sqlite:////"):
        return "/" + database_url.removeprefix("sqlite:////")
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    raise ValueError("Only SQLite DATABASE_URL values are supported by the MVP")


class RunStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._path = sqlite_path(database_url or get_settings().database_url)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS judging_runs (
                    run_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save(self, request: JudgingRequest, result: JudgingResult) -> str:
        run_id = str(uuid4())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO judging_runs(run_id, request_json, result_json) VALUES (?, ?, ?)",
                (run_id, request.model_dump_json(), result.model_dump_json()),
            )
        return run_id

    def get(self, run_id: str) -> tuple[JudgingRequest, JudgingResult] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT request_json, result_json FROM judging_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return (
            JudgingRequest.model_validate_json(row["request_json"]),
            JudgingResult.model_validate_json(row["result_json"]),
        )

    def list_recent(self, limit: int = 20) -> list[JudgingRunSummary]:
        """Return persisted outcomes, never raw prompts, secrets, or DataHub tokens."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT run_id, result_json, created_at FROM judging_runs "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        summaries: list[JudgingRunSummary] = []
        for row in rows:
            result = JudgingResult.model_validate_json(row["result_json"])
            summaries.append(
                JudgingRunSummary(
                    run_id=row["run_id"],
                    created_at=row["created_at"].replace(" ", "T") + "Z",
                    decision=(result.aggregate_decision.decision if result.aggregate_decision else None),
                    openai_status=(result.openai_verdict.verdict if result.openai_verdict else None),
                    groq_status=(result.groq_verdict.verdict if result.groq_verdict else None),
                )
            )
        return summaries


class AnalysisStore:
    """Persist immutable server-generated analysis inputs for later judging."""

    def __init__(self, database_url: str | None = None) -> None:
        self._path = sqlite_path(database_url or get_settings().database_url)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    impact_report_json TEXT NOT NULL,
                    remediation_plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, report: ImpactReport, plan: RemediationPlan) -> str:
        run_id = str(uuid4())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO analysis_runs(
                    run_id, impact_report_json, remediation_plan_json
                ) VALUES (?, ?, ?)
                """,
                (run_id, report.model_dump_json(), plan.model_dump_json()),
            )
        return run_id

    def get(self, run_id: str, repair_cycles: int = 0) -> JudgingRequest | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT impact_report_json, remediation_plan_json
                FROM analysis_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return JudgingRequest(
            impact_report=ImpactReport.model_validate_json(
                row["impact_report_json"]
            ),
            remediation_plan=RemediationPlan.model_validate_json(
                row["remediation_plan_json"]
            ),
            repair_cycles=repair_cycles,
        )

    def restore(self, run_id: str) -> tuple[ImpactReport, RemediationPlan] | None:
        """Return the immutable analysis snapshot without granting judge authority.

        Browser reloads only carry an opaque run identifier.  The report and plan
        are always reloaded from the server-owned SQLite row so client-side data
        can never become the source of truth.
        """

        request = self.get(run_id)
        if request is None:
            return None
        return request.impact_report, request.remediation_plan


run_store = RunStore()
analysis_store = AnalysisStore()
