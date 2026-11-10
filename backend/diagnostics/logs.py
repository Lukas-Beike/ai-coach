"""Bounded, privacy-safe projection of the application log file."""

from __future__ import annotations

import builtins
import json
import re
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
        files and returned in log order. Files are read newest first, one at a
        time, and INFO lines past the limit are skipped without parsing.
        """
        info: builtins.list[tuple[int, dict[str, Any]]] = []
        other: builtins.list[tuple[int, dict[str, Any]]] = []
        position = 0
        for path in reversed(self._paths()):
            if len(info) >= info_limit and len(other) >= non_info_limit:
                break
            if not path.is_file():
                continue
            lines, failure = self._read_lines(path)
            if failure is not None and len(other) < non_info_limit:
                other.append((position, failure))
                position += 1
            position = _collect_lines(
                lines, position, (info, info_limit), (other, non_info_limit)
            )
        kept = sorted([*info, *other], key=lambda item: item[0], reverse=True)
        return self._redactor.sanitize_log_value([entry for _, entry in kept])

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

    def _read_lines(
        self, path: Path
    ) -> tuple[builtins.list[str], dict[str, Any] | None]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failure = {
                "timestamp": self._utc_now(),
                "level": "ERROR",
                "event": "log_read_failed",
                "message": str(exc),
            }
            return [], failure
        return text.splitlines(), None

    def _read_entries(self, paths: Sequence[Path]) -> builtins.list[dict[str, Any]]:
        entries: builtins.list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                continue
            lines, failure = self._read_lines(path)
            if failure is not None:
                entries.append(failure)
            entries.extend(_parse_line(line) for line in lines)
        return entries


_INFO_LINE_RE = re.compile(r'\{(?:"timestamp":\s*"[^"]*",\s*)?"level":\s*"INFO"')


def _parse_line(line: str) -> dict[str, Any]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"level": "UNKNOWN", "event": "unparsed_log", "message": line}


def _collect_lines(
    lines: Sequence[str],
    position: int,
    info: tuple[list[tuple[int, dict[str, Any]]], int],
    other: tuple[list[tuple[int, dict[str, Any]]], int],
) -> int:
    """Add lines newest first to their bounded group; return the next position."""
    for line in reversed(lines):
        group, limit = info if _INFO_LINE_RE.match(line) is not None else other
        if len(group) < limit:
            group.append((position, _parse_line(line)))
            position += 1
    return position
