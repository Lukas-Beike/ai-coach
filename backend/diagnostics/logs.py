"""Bounded, privacy-safe projection of the application log file."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.observability import Redactor


class RecentLogEntriesService:
    """Read recent JSON log entries and redact all projected values."""

    def __init__(
        self,
        log_path: Path,
        redactor: Redactor,
        utc_now: Callable[[], str],
    ) -> None:
        self._log_path = log_path
        self._redactor = redactor
        self._utc_now = utc_now

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self._log_path.is_file():
            return []
        try:
            lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except OSError as exc:
            return [{
                "timestamp": self._utc_now(),
                "level": "ERROR",
                "event": "log_read_failed",
                "message": self._redactor.redact_text(str(exc)),
            }]
        entries: list[dict[str, Any]] = []
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = {"level": "UNKNOWN", "event": "unparsed_log", "message": line}
            entries.append(self._redactor.sanitize_log_value(entry))
        return entries
