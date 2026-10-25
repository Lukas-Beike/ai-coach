"""Shared fixtures for the canonical activity detail tests: a real schema and one activity."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import intervals_snapshot_ingest_plan
from backend.sync.canonical_ingest import ingest_plan

NOW = "2026-10-18T08:00:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
INTERVALS = ProviderId.INTERVALS.value


def open_manager(directory: str | Path, name: str = "detail.db") -> DatabaseManager:
    manager = DatabaseManager(Path(directory) / name, sqlite3, row_factory=row_factory)
    with manager.unit_of_work() as db:
        initialize_schema(db)
    return manager


def seed_intervals_activity(
    manager: DatabaseManager, activity_id: str, **fields: object
) -> None:
    """Ingest one Intervals activity the way a snapshot sync does, so its session exists.

    ``fields`` add or replace keys of the ingested summary row.
    """
    snapshot = {
        "synced_at": NOW,
        "upcoming_calendar": [],
        "provider_sync": {
            "calendar_window": {"start": "2026-09-21", "end": "2026-09-30"},
            "pagination": {},
        },
        "raw_provider_data": {
            "activities": [
                {
                    "id": activity_id,
                    "name": f"Ride {activity_id}",
                    "start_date_local": "2026-09-10T07:00:00",
                    "type": "Ride",
                    **fields,
                }
            ]
        },
    }
    with manager.unit_of_work() as db:
        ingest_plan(
            db,
            intervals_snapshot_ingest_plan(snapshot, zone=ZONE),
            retrieved_at=datetime.fromisoformat(NOW),
            deletion_window=None,
            zone=ZONE,
        )


def add_session_record(
    manager: DatabaseManager,
    provider: ProviderId,
    provider_activity_id: str,
    activity_id: str,
    *,
    recorded_by: str = "garmin",
    sport: str = "ride",
    name: str | None = None,
    merged_into: str | None = None,
    **measured: float,
) -> None:
    """Store one active provider record and, unless it exists, its session.

    ``merged_into`` makes the session a duplicate of that session. ``measured``
    fills activity record columns such as ``duration_s`` or ``distance_m``.
    """
    started_at = "2026-09-10T05:00:00+00:00"
    columns = ", ".join(measured)
    with manager.unit_of_work() as db:
        db.execute(
            "INSERT OR IGNORE INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into, started_at, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                activity_id,
                provider.value,
                provider_activity_id,
                "active" if merged_into is None else "duplicate",
                merged_into,
                started_at,
                NOW,
                NOW,
            ),
        )
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, "
            "activity_id, state, mapper_version, source_kind, recorded_by, sport, "
            "environment, started_at, load_model, name, fetched_at, created_at, "
            f"updated_at{', ' + columns if columns else ''}) VALUES (?, ?, ?, "
            "'active', 1, 'provider_reported', ?, ?, 'outdoor', ?, 'unknown', ?, "
            f"?, ?, ?{', ?' * len(measured)})",
            (
                provider.value,
                provider_activity_id,
                activity_id,
                recorded_by,
                sport,
                started_at,
                name,
                NOW,
                NOW,
                NOW,
                *measured.values(),
            ),
        )
