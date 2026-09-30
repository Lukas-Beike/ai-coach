"""Bounded, privacy-safe projection of the application log file."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable, Sequence
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

    def list(self, limit: int = 200) -> builtins.list[dict[str, Any]]:
        entries = self._read_entries((self._log_path,))
        return entries[-limit:]

    def download(self) -> bytes:
        """Return all current and rotated logs as sanitized JSON Lines."""
        paths = [
            self._log_path.with_name(f"{self._log_path.name}.{index}")
            for index in (3, 2, 1)
        ]
        paths.append(self._log_path)
        entries = self._read_entries(paths)
        return "".join(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            for entry in entries
        ).encode("utf-8")

    def clear(self) -> dict[str, Any]:
        """Clear active log file and remove rotated logs."""
        cleared = False
        if self._log_path.parent.is_dir():
            for path in self._log_path.parent.glob(f"{self._log_path.name}.*"):
                if path.is_file():
                    path.unlink()
                    cleared = True
        if self._log_path.is_file():
            self._log_path.write_text("", encoding="utf-8")
            cleared = True
        return {"ok": True, "cleared": cleared}

    def _read_entries(self, paths: Sequence[Path]) -> builtins.list[dict[str, Any]]:
        entries: builtins.list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                entries.append(
                    {
                        "timestamp": self._utc_now(),
                        "level": "ERROR",
                        "event": "log_read_failed",
                        "message": self._redactor.redact_text(str(exc)),
                    }
                )
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = {
                        "level": "UNKNOWN",
                        "event": "unparsed_log",
                        "message": line,
                    }
                entries.append(self._redactor.sanitize_log_value(entry))
        return entries
