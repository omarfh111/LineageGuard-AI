"""Deterministic request-interpreter agent for governed change assessments."""

from __future__ import annotations

from app.domain.contracts import ChangeRequest


class RequestInterpreter:
    """Normalize an already validated request without calling an LLM."""

    def interpret(self, request: ChangeRequest) -> ChangeRequest:
        return request.model_copy(
            update={
                "reason": " ".join(request.reason.split()),
                "column_name": request.column_name.strip() if request.column_name else None,
                "new_value": request.new_value.strip() if request.new_value else None,
            }
        )
