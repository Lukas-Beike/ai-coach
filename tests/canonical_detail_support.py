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


def seed_intervals_activity(manager: DatabaseManager, activity_id: str) -> None:
    """Ingest one Intervals activity the way a snapshot sync does, so its session exists."""
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
