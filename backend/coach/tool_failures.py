"""Project structured Coach tool failures into receipts and safe logs."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from backend.coach.turn_failures import coach_error_metadata
from backend.errors import AppError


class CoachStructuredToolFailureService:
    """Keep tool-failure receipts and diagnostics consistent and redacted."""

    def __init__(
        self,
        repository_root: Path,
        logger: logging.Logger,
        allowed_tool_names: frozenset[str],
    ) -> None:
        self._repository_root = repository_root
        self._logger = logger
        self._allowed_tool_names = allowed_tool_names

    def project(
        self,
        exc: BaseException,
        *,
        name: str,
        call_id: str,
        effect_key: str,
        step_key: str,
        repair_key: str | None,
        scope_repair_key: str | None,
        request_binding_key: str | None,
        plan_effect_key: str | None,
        action: dict[str, Any],
        command_receipts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = {
            "ok": False,
            "reason": getattr(exc, "reason", "tool_arguments_invalid"),
            "error": str(exc)
            if isinstance(exc, AppError)
            else "Die Werkzeugargumente sind ungültig. Prüfe das Schema und den aktuellen Zustand und korrigiere den Aufruf.",
        }
        validation_reason = str(getattr(exc, "validation_reason", "") or "").strip()
        if validation_reason and re.fullmatch(r"request_[a-z_]{1,72}", validation_reason):
            result["validation_reason"] = validation_reason
        if not result["reason"]:
            result["reason"] = (
                "tool_arguments_invalid"
                if isinstance(exc, AppError) and exc.status == 400
                else "tool_failed"
            )
        technical_error = coach_error_metadata(exc, self._repository_root)
        command_receipts.append(
            {
                "call_id": call_id,
                "tool": name,
                "effect_key": effect_key,
                "step_key": step_key,
                "repair_key": repair_key,
                "scope_repair_key": scope_repair_key,
                "request_binding_key": request_binding_key,
                "plan_effect_key": plan_effect_key,
                "request": action.get("request"),
                "result": result,
                "diagnostic_error": technical_error,
            }
        )
        self._logger.warning(
            "Coach step failed",
            extra={
                "event": "coach_tool_failed",
                "context": {
                    "tool": name if name in self._allowed_tool_names else "unknown",
                    **technical_error,
                },
            },
        )
        return result
