"""Recovery copies and purge markers the app keeps beside the database.

A restore and the one-time Intervals.icu purge each save an encrypted copy of
the whole database in the data directory, and the purge leaves a marker file
there. Local privacy deletion removes them with the database content: a copy
holds exactly the data the athlete asked to erase.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# ``<database>.<label>-<timestamp>-<id>`` as written by the restore service and,
# in release 2.0.0, by the Intervals.icu purge (removed; its copies stay on disk).
_COPY_LABELS = r"(?:pre-restore|pre-intervals-purge-v\d+)"
_MARKER_PATTERN = re.compile(r"intervals-purge-v\d+\.done")


@dataclass(frozen=True)
class RecoveryCopyErasure:
    removed: int
    failed: int


class RecoveryCopies:
    """The recovery copies and purge markers of one data directory."""

    def __init__(self, data_dir: Path, database_name: str) -> None:
        self._data_dir = data_dir
        self._copy_pattern = re.compile(
            rf"{re.escape(database_name)}\.{_COPY_LABELS}-\d{{14}}-[0-9a-f]{{32}}"
        )

    def paths(self) -> list[Path]:
        try:
            with os.scandir(self._data_dir) as entries:
                return sorted(
                    Path(entry.path)
                    for entry in entries
                    if entry.is_file(follow_symlinks=False)
                    and (
                        self._copy_pattern.fullmatch(entry.name)
                        or _MARKER_PATTERN.fullmatch(entry.name)
                    )
                )
        except OSError:
            return []

    def count(self) -> int:
        return len(self.paths())

    def erase(self) -> RecoveryCopyErasure:
        removed = failed = 0
        for path in self.paths():
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                failed += 1
        return RecoveryCopyErasure(removed=removed, failed=failed)
