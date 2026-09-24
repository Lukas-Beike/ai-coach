"""Bounded, privacy-safe history for persisted Coach commands."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Collection
from typing import Any

from backend import observability

_STATUSES = frozenset({"queued", "running", "completed", "partial", "failed", "cancelled"})
_RESPONSE_STATUSES = _STATUSES | {"incomplete"}


class CoachDiagnosticHistoryService:
    """Read and safely project recent Coach command receipts."""

    def __init__(
        self,
        database: Callable[[], Any],
        db_lock: Any,
        redact: Callable[[Any], Any],
        receipt_parser: Callable[[Any], dict[str, Any]],
        allowed_tools: Collection[str],
    ) -> None:
        self._database = database
        self._db_lock = db_lock
        self._redact = redact
        self._receipt_parser = receipt_parser
        self._allowed_tools = frozenset(allowed_tools)

    def history(self) -> list[dict[str, Any]]:
        """Return up to 20 entries without dialogue, arguments, or results."""
        with self._db_lock, self._database() as db:
            rows = db.execute(
                "SELECT client_turn_id, receipt, created_at, updated_at "
                "FROM coach_commands "
                "ORDER BY created_at DESC, client_turn_id DESC LIMIT 20"
            ).fetchall()
        return [self._history_entry(row) for row in rows]

    def _history_entry(self, row: Any) -> dict[str, Any]:
        receipt = self._receipt_parser(row["receipt"])
        status = receipt.get("status")
        response_status = receipt.get("response_status")
        return {
            "id": hashlib.sha256(str(row["client_turn_id"]).encode()).hexdigest()[:12],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": status if isinstance(status, str) and status in _STATUSES else "unknown",
            "response_status": (
                response_status
                if isinstance(response_status, str) and response_status in _RESPONSE_STATUSES
                else None
            ),
            "awaiting_clarification": receipt.get("awaiting_clarification") is True,
            "error": self._error_metadata(receipt.get("diagnostic_error")),
            "steps": self._command_steps(receipt),
        }

    def _command_steps(self, receipt: dict[str, Any]) -> list[dict[str, Any]]:
        command_receipts = receipt.get("command_receipts")
        if not isinstance(command_receipts, list):
            return []
        steps = []
        for step in command_receipts[:40]:
            if not isinstance(step, dict):
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            tool = step.get("tool")
            steps.append({
                "tool": tool if isinstance(tool, str) and tool in self._allowed_tools else "unknown",
                "ok": result.get("ok") is True,
                "error": self._error_metadata(step.get("diagnostic_error")),
            })
        return steps

    def _error_metadata(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        result: dict[str, Any] = {}
        for key in ("type", "reason", "validation_reason"):
            item = value.get(key)
            if isinstance(item, str) and re.fullmatch(r"(?a:[A-Za-z_]{1,80})", item):
                result[key] = item
        provider_code = value.get("provider_error_code")
        if isinstance(provider_code, str) and provider_code in observability.OPENAI_RESPONSE_ERROR_CODES:
            result["provider_error_code"] = provider_code
        status = value.get("status")
        if isinstance(status, int) and 100 <= status <= 599:
            result["status"] = status
        frames = value.get("frames")
        if isinstance(frames, (list, tuple)):
            safe_frames = [frame for frame in (self._frame(item) for item in frames[-8:]) if frame]
            if safe_frames:
                result["frames"] = safe_frames
        return self._redact(result)

    @staticmethod
    def _frame(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        filename, function, line = value.get("file"), value.get("function"), value.get("line")
        if not (
            isinstance(filename, str)
            and re.fullmatch(r"(?:server\.py|backend/(?:[a-z_]+/)*[a-z_]+\.py)", filename)
            and isinstance(function, str)
            and re.fullmatch(r"(?a:(?!\d)\w{1,101})", function)
            and isinstance(line, int)
            and 0 < line < 1_000_000
        ):
            return None
        return {"file": filename, "function": function, "line": line}
