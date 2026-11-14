"""Dry run of the aerobic decoupling eligibility (card M8, #1773) on a COPY of the database.

The script opens the copy with the key in ``APP_PASSWORD`` (never printed), as
the application does. Inside one transaction it upgrades the schema if needed,
evaluates the report of ``backend.performance.decoupling_eligibility`` (gates,
rules and measures are described there; the diagnostics section
``decoupling_eligibility`` reports the same) over the last ``--days`` (365) days,
and rolls everything back: the file is left unchanged. It prints the
counts-only JSON report to stdout. No ids, names, dates or single-session values.

Run it on a disposable copy only, in a container without network access::

    docker build -t pacecraft:local .
    docker network create --internal pacecraft-dry-run
    docker run --rm --network pacecraft-dry-run -e APP_PASSWORD \\
      -v "<copy directory>:/copy" \\
      -v "<repository>/scripts/decoupling_eligibility_dry_run.py:/app/scripts/decoupling_eligibility_dry_run.py:ro" \\
      pacecraft:local python -m scripts.decoupling_eligibility_dry_run /copy/intervals-coach.db

``-e APP_PASSWORD`` passes the variable from the calling shell without writing
its value on the command line. The copy directory must be writable for SQLite's
temporary WAL files; the database file itself is not modified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import configure_cipher
from backend.performance import decoupling_eligibility as eligibility
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_metrics import analysis_activity


class _RolledBack(Exception):
    """Carries the report out of the transaction, which it rolls back."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("dry run rolled back")
        self.report = report


def _report(db: Any, days: int, today: date) -> dict[str, Any]:
    selection = eligibility.select(
        db,
        CanonicalTableReader().activity_sessions,
        KeyValueRepository(lambda: ""),
        today,
        days,
    )
    return eligibility.report(
        selection,
        lambda session_id: eligibility.evaluate(
            analysis_activity(db, session_id, selection.sessions[session_id])
        ),
    )


def dry_run(
    path: Path,
    password: str,
    *,
    backend: Any,
    configure: Callable[[Any, str], None] | None = configure_cipher,
    days: int = eligibility.DEFAULT_DAYS,
    today: date | None = None,
) -> dict[str, Any]:
    """Evaluate ``path`` inside one transaction, roll back, and return the report."""
    if not path.is_file():
        raise FileNotFoundError("database copy not found")
    manager = DatabaseManager(
        path,
        backend,
        password=password,
        configure=configure,
        row_factory=row_factory,
        reader_count=1,
        persist_connections=False,
    )
    try:
        with manager.unit_of_work() as db:
            migrate_schema(db)
            day = today or datetime.now(UTC).date()
            raise _RolledBack({"rolled_back": True, **_report(db, days, day)})
    except _RolledBack as rolled_back:
        return rolled_back.report
    finally:
        manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path, help="path to a COPY of the database")
    parser.add_argument(
        "--days", type=int, default=eligibility.DEFAULT_DAYS, help="look-back days"
    )
    arguments = parser.parse_args(argv)
    password = os.environ.get("APP_PASSWORD", "")
    if len(password) < 12:
        print("APP_PASSWORD must be set (at least 12 characters).", file=sys.stderr)
        return 2
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        print("SQLCipher is required; run the script in the image.", file=sys.stderr)
        return 2
    report = dry_run(
        arguments.database, password, backend=sqlcipher, days=arguments.days
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
