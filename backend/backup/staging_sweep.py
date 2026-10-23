"""Remove export, restore and backup staging files left by an interrupted run."""

from __future__ import annotations

import logging
import os
from fnmatch import fnmatchcase
from pathlib import Path

# Every producer creates these names directly in the data directory: the privacy
# export (export.py), restore staging (restore_validation.py) and database backup
# snapshots (database.py). The staged SQLite files may leave their own journal,
# WAL and SHM sidecars. The live database, its sidecars, pre-restore copies and
# the Garmin token store never match.
_SQLITE_SIDECAR_SUFFIXES = ("", "-journal", "-wal", "-shm")
ORPHANED_STAGING_PATTERNS = (
    ("privacy_export", ".intervals-coach-export-*.zip"),
    *(
        ("restore_staging", f".intervals-coach-restore-*.db{suffix}")
        for suffix in _SQLITE_SIDECAR_SUFFIXES
    ),
    *(
        ("database_backup", f".database-backup-*.tmp{suffix}")
        for suffix in _SQLITE_SIDECAR_SUFFIXES
    ),
)


def remove_orphaned_staging_files(data_dir: Path, logger: logging.Logger) -> None:
    """Delete matching regular files in the data directory; run before any worker."""
    try:
        with os.scandir(data_dir) as entries:
            matches = [
                (kind, entry.path)
                for entry in entries
                if entry.is_file(follow_symlinks=False)
                for kind, pattern in ORPHANED_STAGING_PATTERNS
                if fnmatchcase(entry.name, pattern)
            ]
    except OSError as exc:
        _log_failure(logger, "data_directory", exc)
        return
    removed = 0
    for kind, path in matches:
        try:
            os.unlink(path)
            removed += 1
        except OSError as exc:
            _log_failure(logger, kind, exc)
    if removed:
        logger.info(
            "Orphaned staging files removed",
            extra={"event": "backup_staging_removed", "context": {"count": removed}},
        )


def _log_failure(logger: logging.Logger, kind: str, exc: OSError) -> None:
    logger.warning(
        "Orphaned staging cleanup failed",
        extra={
            "event": "backup_staging_cleanup_failed",
            "context": {"kind": kind, "error_class": type(exc).__name__},
        },
    )
