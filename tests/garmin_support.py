"""Store and read Garmin collections through the per-element tables in tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from server_test_support import server  # configures the test environment first

from backend.canonical.garmin_payload import SECTIONS, STATE_KEY
from backend.db import garmin_store
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

SYNCED_AT = "2026-08-30T08:00:00+00:00"


def _stamped(payload: dict[str, Any]) -> dict[str, Any]:
    """Give a fixture payload a readable fetch time, which the writer needs for rows."""
    try:
        datetime.fromisoformat(str(payload.get("synced_at")))
    except ValueError:
        return {**payload, "synced_at": SYNCED_AT}
    return payload


def clear_garmin(db: Any) -> None:
    """Drop the stored Garmin sections and state, like starting from no collection."""
    for section in SECTIONS:
        garmin_store.prune_section(db, section, set())
    db.execute("DELETE FROM kv WHERE key = ?", (STATE_KEY,))


def store_garmin(db: Any, payload: dict[str, Any], *, replace: bool = True) -> None:
    """Write a whole collection payload; ``replace`` first clears the stored one."""
    if replace:
        clear_garmin(db)
    GarminSnapshotWriter(server.KEY_VALUE_REPOSITORY, lambda: UTC).write(
        db, _stamped(payload)
    )


def save_garmin(payload: dict[str, Any], *, replace: bool = True) -> None:
    """Store a collection through the running test server's database."""
    with server.database_manager().unit_of_work() as db:
        store_garmin(db, payload, replace=replace)


def read_garmin() -> dict[str, Any]:
    """Return everything stored for Garmin as one payload-shaped view."""
    with server.database_manager().reader() as db:
        return garmin_store.read_view(db)
