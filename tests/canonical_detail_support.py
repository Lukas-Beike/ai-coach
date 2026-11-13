"""Shared fixtures for the canonical activity detail tests: a real schema and one activity."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from intervals_plan_stub import intervals_ingest_plan

from backend.canonical.vocabulary import ProviderId, StreamChannel
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import DatabaseBusyError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_ingest import ingest_plan

NOW = "2026-10-18T08:00:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
INTERVALS = ProviderId.INTERVALS.value
# The canonical channel of each legacy stream key the tests store.
STREAM_KEY_CHANNELS = {
    "time": StreamChannel.TIME_S,
    "distance": StreamChannel.DISTANCE_M,
    "altitude": StreamChannel.ALTITUDE_M,
    "grade_smooth": StreamChannel.GRADE_PCT,
    "grade": StreamChannel.GRADE_PCT,
    "velocity_smooth": StreamChannel.SPEED_MPS,
    "velocity": StreamChannel.SPEED_MPS,
    "speed": StreamChannel.SPEED_MPS,
    "watts": StreamChannel.POWER_W,
    "power": StreamChannel.POWER_W,
    "heartrate": StreamChannel.HEART_RATE_BPM,
    "cadence": StreamChannel.CADENCE_RPM,
    "temperature": StreamChannel.TEMPERATURE_C,
    "moving": StreamChannel.MOVING,
}


def _writer_free(manager: DatabaseManager) -> bool:
    """Whether another thread gets the writer at once."""
    taken: list[bool] = []

    def attempt() -> None:
        try:
            with manager.unit_of_work(timeout=0):
                taken.append(True)
        except DatabaseBusyError:
            taken.append(False)

    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join(5)
    return taken == [True]


def writer_free_while_computing(
    manager: DatabaseManager, stage: Any, module: ModuleType, name: str
) -> list[bool]:
    """Run ``stage`` in the backfill worker until it is complete; per call of
    ``module.name`` (its per-session computation), whether the writer was free
    meanwhile (#2311)."""
    free: list[bool] = []
    compute = getattr(module, name)

    def probe(*args: Any, **kwargs: Any) -> Any:
        free.append(_writer_free(manager))
        return compute(*args, **kwargs)

    worker = CanonicalBackfillWorker(
        backfill=Mock(run_batch=Mock(return_value=BatchReport(items=0, done=True))),
        database=lambda: manager,
        maintenance_gate=MaintenanceGate(),
        poll_seconds=0,
        followups=[stage],
    )
    with patch.object(module, name, probe):
        worker.start()
        try:
            worker.join(30)
        finally:
            worker.stop()
            worker.join(5)
    return free


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
            intervals_ingest_plan(
                snapshot["raw_provider_data"],
                zone=ZONE,
                retrieved_at=datetime.fromisoformat(NOW),
            ),
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
    started_at: str = "2026-09-10T05:00:00+00:00",
    **measured: float,
) -> None:
    """Store one active provider record and, unless it exists, its session.

    ``merged_into`` makes the session a duplicate of that session. ``measured``
    fills activity record columns such as ``duration_s`` or ``distance_m``.
    """
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


def store_garmin_streams(
    manager: DatabaseManager,
    garmin_id: str,
    streams: dict,
    laps: list[dict] | None = None,
) -> None:
    """Store full streams (and laps) on the existing Garmin record ``garmin_id``.

    ``streams`` uses the legacy stream keys.
    """
    from backend.canonical.activity_detail import (
        ActivityLap,
        ActivityLapSet,
        ActivityStreamSet,
    )
    from backend.canonical.records import Provenance
    from backend.canonical.vocabulary import (
        ActivityDetailOrigin,
        LapKind,
        LapSource,
        RecordingOrigin,
        SourceKind,
        StreamResolution,
    )
    from backend.db.activity_detail_store import replace_detail_set

    provenance = Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=datetime.fromisoformat(NOW),
        label="Garmin Connect",
    )
    with manager.unit_of_work() as db:
        replace_detail_set(
            db,
            ActivityStreamSet(
                provider_activity_id=garmin_id,
                provenance=provenance,
                origin=ActivityDetailOrigin.FETCH,
                resolution=StreamResolution.FULL,
                channels={
                    STREAM_KEY_CHANNELS[key]: tuple(
                        None if value is None else float(value) for value in values
                    )
                    for key, values in streams.items()
                },
            ),
            mapper_version=1,
            summary_sha256=None,
            now=NOW,
        )
        if laps:
            replace_detail_set(
                db,
                ActivityLapSet(
                    provider_activity_id=garmin_id,
                    provenance=provenance,
                    origin=ActivityDetailOrigin.FETCH,
                    lap_source=LapSource.DEVICE_LAPS,
                    laps=tuple(
                        ActivityLap(
                            index=index,
                            kind=LapKind.LAP,
                            start_offset_s=float(lap["start_time"]),
                            end_offset_s=float(lap["end_time"]),
                        )
                        for index, lap in enumerate(laps)
                    ),
                ),
                mapper_version=1,
                summary_sha256=None,
                now=NOW,
            )


def add_garmin_copy(
    manager: DatabaseManager,
    intervals_id: str,
    streams: dict,
    laps: list[dict] | None = None,
) -> str:
    """Bundle a Garmin copy with full streams (and laps) into an Intervals session.

    The activity detail document reads Garmin, Wahoo and local detail only
    (#1685), so tests that stored Intervals.icu streams use this copy instead.
    Returns the Garmin activity id.
    """
    garmin_id = f"garmin-{intervals_id}"
    with manager.unit_of_work() as db:
        row = db.execute(
            "SELECT activity_id, sport, environment, started_at, name "
            "FROM activity_records WHERE provider = ? AND provider_activity_id = ?",
            (INTERVALS, intervals_id),
        ).fetchone()
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, "
            "activity_id, state, mapper_version, source_kind, recorded_by, sport, "
            "environment, started_at, load_model, name, fetched_at, created_at, "
            "updated_at) VALUES ('garmin', ?, ?, 'active', 1, 'provider_reported', "
            "'garmin', ?, ?, ?, 'unknown', ?, ?, ?, ?)",
            (
                garmin_id,
                row["activity_id"],
                row["sport"],
                row["environment"],
                row["started_at"],
                row["name"],
                NOW,
                NOW,
                NOW,
            ),
        )
    store_garmin_streams(manager, garmin_id, streams, laps)
    return garmin_id
