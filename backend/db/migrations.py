"""Schema gate for existing encrypted application databases.

The oldest supported schema is version 9, written by release 1.13.x. Older
databases and backups are rejected unchanged; upgrade them with release 1.13.6
first. When CURRENT_SCHEMA_VERSION is bumped, freeze the outgoing schema as a
fixture and add a versioned, transactional upgrade step here.
"""

from __future__ import annotations

from typing import Any

from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current

_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)


def migrate_schema(db: Any) -> None:
    """Accept only the current schema; reject anything else without writing."""
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if version != CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            "Die Datenbankversion wird von diesem Release nicht unterstützt."
        )
    if not database_schema_is_current(db):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MESSAGE)
