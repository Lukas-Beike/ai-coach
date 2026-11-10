"""Bounded, privacy-safe projection of the application log file."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from backend.observability import LOG_BACKUP_COUNT, Redactor

REPORT_NON_INFO_ENTRIES = 200
REPORT_INFO_ENTRIES = 100


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
        """Return the last ``limit`` lines of the active log file."""
        entries = self._read_entries((self._log_path,))[-limit:]
        return self._redactor.sanitize_log_value(entries)

    def report_entries(
        self,
        non_info_limit: int = REPORT_NON_INFO_ENTRIES,
        info_limit: int = REPORT_INFO_ENTRIES,
    ) -> builtins.list[dict[str, Any]]:
        """Return the latest warnings and errors plus the latest INFO lines.

        Routine INFO traffic must not push an overnight failure out of the
        report, so the two groups are limited separately across all rotated
        files and returned in log order.
        """
        entries = self._read_entries(self._paths())
        info = [i for i, entry in enumerate(entries) if _level(entry) == "INFO"]
        other = [i for i, entry in enumerate(entries) if _level(entry) != "INFO"]
        keep = sorted({*other[-non_info_limit:], *info[-info_limit:]})
        return self._redactor.sanitize_log_value([entries[i] for i in keep])

    def download(self) -> bytes:
        """Return all current and rotated logs as sanitized JSON Lines."""
        entries = self._redactor.sanitize_log_value(self._read_entries(self._paths()))
        return "".join(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            for entry in entries
        ).encode("utf-8")

    def _paths(self) -> builtins.list[Path]:
        """Rotated files oldest first, then the active file."""
        paths = [
            self._log_path.with_name(f"{self._log_path.name}.{index}")
            for index in range(LOG_BACKUP_COUNT, 0, -1)
        ]
        paths.append(self._log_path)
        return paths

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
                        "message": str(exc),
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
                entries.append(entry)
        return entries


def _level(entry: Any) -> str:
    return str(entry.get("level", "")) if isinstance(entry, dict) else ""
