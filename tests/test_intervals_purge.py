"""The Intervals.icu ingest purge (#1728) on a populated released v21 database.

The only production instance runs schema v21 (release 1.13.44). Each case loads
the frozen v21 fixture into temporary storage, stores a realistic mix of bundled
sessions, athlete data, ingest rows and output ids, upgrades it to the current
schema as the application does, and runs the purge. Synthetic rows only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from backend import change_history
from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.profile import normalize_profile
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db import canonical_store, row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import ActivityFeedbackRepository, KeyValueRepository
from backend.diagnostics.intervals_purge import summarize_intervals_purge
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.providers.canonical_plans import current_observation_mapper_versions
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import intervals_purge
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.intervals import IntervalsSyncService
from backend.sync.intervals_ingest import (
    IntervalsIngestSwitch,
    ingest_off_result,
    purge_marker_exists,
)
from backend.sync.intervals_purge import (
    BACKUP_LABEL,
    IntervalsPurgeRunner,
    intervals_row_counts,
    purge_status,
    run_purge,
)
from scripts import intervals_purge_dry_run

FIXTURE = Path(__file__).with_name("fixtures") / "schema_v21.sql.txt"
EARLY = "2026-10-01T06:00:00+00:00"
LATER = "2026-10-01T07:00:00+00:00"
OLD_FEEDBACK = "2026-10-02T08:00:00+00:00"
NEW_FEEDBACK = "2026-10-03T08:00:00+00:00"
NOW = "2026-11-07T09:00:00+00:00"
DIGEST = "e" * 64
ICU = "intervals"
TARGETS = {"steps": [{"watts": 250}]}
RATING_STATE = "garmin_rating_backfill_state"
FEEDBACK_HISTORY_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_HISTORY_ID = "22222222-2222-2222-2222-222222222222"
BUNDLE_HISTORY_ID = "33333333-3333-3333-3333-333333333333"
GARMIN_HISTORY_ID = "44444444-4444-4444-4444-444444444444"
OLDEST = "2026-10-01T09:00:00+00:00"
# Kept output state and settings (key -> value).
KEPT_KEYS = {
    "last_library_sync_at": NOW,
    "activity_detail_prefetch_floor": "2026-01-01",
    "garmin_equipment_initialized": "1",
    "planned_units_initial_import_at": NOW,
}
INGEST_KEYS = {
    "last_sync_at": NOW,
    "last_sync_error": "",
    "sync_running": "0",
    "sync_status": "ok",
    "intervals_full_window_read_on": "2026-11-06",
    "performance_refresh_running": "0",
    "last_performance_refresh_at": NOW,
    "intervals_full_resync_status": "",
    "activity_detail:" + "a" * 64: "{}",
    "activity_detail_failure:" + "b" * 64: "{}",
    "activity_detail_backfill_state": "{}",
    "activity_detail_retirement_state": "{}",
    "canonical_coverage:intervals": "{}",
}


def origin(provider: str) -> str:
    """The recording origin: Intervals.icu copies relay Garmin recordings."""
    return "garmin" if provider == ICU else provider


def _session(
    db: Any,
    session: str,
    provider: str,
    provider_id: str,
    *,
    created: str = EARLY,
    state: str = "active",
    merged_into: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, state, merged_into, started_at, local_date, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, '2026-10-01', ?, ?)",
        (session, provider, provider_id, state, merged_into, EARLY, created, created),
    )
    db.execute(
        "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
        "state, mapper_version, source_kind, recorded_by, sport, environment, "
        "started_at, local_date, duration_s, moving_duration_s, normalized_power, "
        "load_model, fetched_at, created_at, updated_at) VALUES (?, ?, ?, 'active', "
        "1, 'provider_reported', ?, 'ride', 'outdoor', ?, '2026-10-01', 3600, 3600, "
        "200, 'unknown', ?, ?, ?)",
        (
            provider,
            provider_id,
            session,
            origin(provider),
            EARLY,
            EARLY,
            created,
            created,
        ),
    )
    db.execute(
        "INSERT INTO provider_records(provider, record_kind, source_record_id, "
        "payload, payload_hash, fetched_at, mapped_version, created_at, updated_at) "
        "VALUES (?, 'activity', ?, '{}', ?, ?, 1, ?, ?)",
        (provider, provider_id, DIGEST, EARLY, EARLY, EARLY),
    )


def _bundles(db: Any) -> None:
    """Intervals.icu+Garmin both ways, Intervals.icu only, Wahoo+Intervals.icu."""
    _session(db, "act_ivl_a", ICU, "ivl-101")
    _session(
        db,
        "act_gar_a",
        "garmin",
        "gar-201",
        created=LATER,
        state="duplicate",
        merged_into="act_ivl_a",
    )
    _session(db, "act_gar_b", "garmin", "gar-202")
    _session(
        db,
        "act_ivl_b",
        ICU,
        "ivl-102",
        created=LATER,
        state="duplicate",
        merged_into="act_gar_b",
    )
    _session(db, "act_ivl_only", ICU, "ivl-103")
    _session(db, "act_ivl_c", ICU, "ivl-104")
    _session(
        db,
        "act_wah_c",
        "wahoo",
        "wah-301",
        created=LATER,
        state="duplicate",
        merged_into="act_ivl_c",
    )
    _session(db, "act_gar_x", "garmin", "gar-203")


def _feedback(
    db: Any,
    key: str,
    notes: str,
    updated: str,
    *,
    provider: str | None = None,
    session: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO activity_feedback(activity_id, notes, session_rpe, created_at, "
        "updated_at, provider, session_id) VALUES (?, ?, 5, ?, ?, ?, ?)",
        (key, notes, updated, updated, provider, session),
    )


def _athlete_data(db: Any) -> None:
    # Under an Intervals.icu record id, before sessions were stored.
    _feedback(db, "ivl-101", "moved", OLD_FEEDBACK, provider=ICU)
    # Colliding pair: the newer Intervals.icu row wins over the session-id row.
    _feedback(db, "act_gar_b", "older resident", OLD_FEEDBACK)
    _feedback(
        db, "ivl-102", "newer moved", NEW_FEEDBACK, provider=ICU, session="act_ivl_b"
    )
    # Colliding pair: the newer session-id row stays.
    _feedback(db, "act_wah_c", "newer resident", NEW_FEEDBACK)
    _feedback(db, "ivl-104", "older moved", OLD_FEEDBACK, provider=ICU)
    _feedback(db, "ivl-103", "lost", OLD_FEEDBACK, provider=ICU)
    _feedback(db, "ivl-999", "unresolved", OLD_FEEDBACK, provider=ICU)
    _feedback(db, "act_gar_x", "untouched", OLD_FEEDBACK, session="act_gar_x")
    # Stored under the survivor's own provider id: in its key family, older.
    _feedback(db, "gar-202", "oldest family row", OLDEST, provider="garmin")
    # Moved, lost on the Intervals.icu-only session, and a collision the newer
    # assignment of the Wahoo session wins.
    for key, observed in (
        ("ivl-101", OLD_FEEDBACK),
        ("act_ivl_only", OLD_FEEDBACK),
        ("ivl-104", OLD_FEEDBACK),
        ("act_wah_c", NEW_FEEDBACK),
        ("gar-201", OLDEST),
    ):
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (
                "equipment_assignment:" + key,
                json.dumps(
                    {
                        "activity_id": key,
                        "equipment_id": "eq-1",
                        "observed_at": observed,
                    }
                ),
                observed,
            ),
        )
    for session, targets in (
        ("act_ivl_a", TARGETS),
        ("act_ivl_c", TARGETS),
        ("act_wah_c", None),
        ("act_ivl_only", TARGETS),
    ):
        db.execute(
            "INSERT INTO activity_detail_analysis(activity_id, analysis_version, "
            "input_sha256, payload, computed_at, created_at, updated_at) "
            "VALUES (?, 3, ?, ?, ?, ?, ?)",
            (
                session,
                DIGEST,
                json.dumps({"target_snapshot": targets, "stale": False}),
                EARLY,
                EARLY,
                EARLY,
            ),
        )
    for change_id, entity_type, entity_id in (
        (FEEDBACK_HISTORY_ID, "activity_feedback", "session:act_ivl_a"),
        (PROFILE_HISTORY_ID, "profile", "profile"),
        (BUNDLE_HISTORY_ID, "activity_session", "act_gar_a,act_ivl_a"),
        (GARMIN_HISTORY_ID, "activity_session", "act_gar_x"),
    ):
        db.execute(
            "INSERT INTO change_history(id, entity_type, entity_id, action, source, "
            "created_at, before_hash, after_hash, diff) "
            "VALUES (?, ?, ?, 'update', 'local', ?, ?, ?, ?)",
            (
                change_id,
                entity_type,
                entity_id,
                OLD_FEEDBACK,
                DIGEST,
                DIGEST,
                json.dumps({"fields": {}, "before_present": True}),
            ),
        )
    db.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES ('profile', ?, ?)",
        (
            json.dumps(
                {
                    "name": "Athlete",
                    "preferred_source_body": ICU,
                    "preferred_source_hrv": "garmin",
                }
            ),
            EARLY,
        ),
    )


def _ingest_rows(db: Any) -> None:
    db.execute(
        "INSERT INTO activity_detail_sets(provider, provider_activity_id, detail_kind, "
        "mapper_version, origin, source_kind, recorded_by, resolution, content_sha256, "
        "fetched_at, created_at, updated_at) VALUES (?, 'ivl-101', 'streams', 1, "
        "'fetch', 'provider_reported', ?, 'full', ?, ?, ?, ?)",
        (ICU, origin(ICU), DIGEST, EARLY, EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO activity_stream_channels(provider, provider_activity_id, channel, "
        "point_count, valid_count, data) VALUES (?, 'ivl-101', 'time_s', 1, 1, ?)",
        (ICU, b"\x00" * 8),
    )
    for provider, key in ((ICU, "ivl-rhr"), ("garmin", "gar-rhr")):
        db.execute(
            "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
            "recorded_by, provider, observed_on, mapper_version, created_at, updated_at) "
            "VALUES (?, 'resting_hr', 48, 'bpm', 'provider_reported', ?, ?, "
            "'2026-10-01', 1, ?, ?)",
            (key, origin(provider), provider, EARLY, EARLY),
        )
    # The Garmin FTP the local session load (M6) of every ride uses.
    db.execute(
        "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
        "recorded_by, provider, sport, observed_on, mapper_version, created_at, "
        "updated_at) VALUES ('gar-ftp', 'ftp', 250, 'W', 'provider_reported', "
        "'garmin', 'garmin', 'ride', '2026-09-01', ?, ?, ?)",
        (current_observation_mapper_versions()["garmin"], EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO provider_records(provider, record_kind, source_record_id, payload, "
        "payload_hash, fetched_at, created_at, updated_at) VALUES (?, 'wellness', "
        "'2026-10-01', '{}', ?, ?, ?, ?)",
        (ICU, DIGEST, EARLY, EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO zone_configurations(config_key, provider, sport, metric, "
        "threshold, limits, source_kind, recorded_by, source_record_id, mapper_version, "
        "created_at, updated_at) VALUES ('ivl-zones', ?, 'ride', 'power', 250, "
        "'[150, 200, 250, 300]', 'provider_reported', ?, 'ivl-athlete', 1, ?, ?)",
        (ICU, origin(ICU), EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO sleep_periods(provider, started_at, ended_at, wake_date, kind, "
        "source_kind, recorded_by, source_record_id, mapper_version, created_at, "
        "updated_at) VALUES (?, ?, ?, '2026-10-01', 'main', 'provider_reported', ?, "
        "'ivl-sleep', 1, ?, ?)",
        (ICU, EARLY, LATER, origin(ICU), EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO power_curve_points(provider, duration_s, watts, observed_on, "
        "source_kind, recorded_by, source_record_id, mapper_version, created_at, "
        "updated_at) VALUES (?, 60, 400, '2026-10-01', 'provider_reported', ?, "
        "'ivl-curve', 1, ?, ?)",
        (ICU, origin(ICU), EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO power_curve_fetches(provider, source_record_id, fetch_status, "
        "source_kind, recorded_by, mapper_version, created_at, updated_at) VALUES "
        "(?, 'ivl-curve', 'ok', 'provider_reported', ?, 1, ?, ?)",
        (ICU, origin(ICU), EARLY, EARLY),
    )
    db.execute("INSERT INTO snapshots(payload, created_at) VALUES ('{}', ?)", (EARLY,))
    for provider in (ICU, "garmin"):
        db.execute(
            "INSERT INTO provider_sync_cursors(provider, stream, cursor, updated_at) "
            "VALUES (?, 'historical', '2026-01-01', ?)",
            (provider, EARLY),
        )
    for job_id, provider, job_type in (
        ("job-refresh", ICU, "refresh"),
        ("job-push", ICU, "plan_push"),
        ("job-garmin", "garmin", "refresh"),
    ):
        db.execute(
            "INSERT INTO sync_jobs(id, provider, type, status, payload, requested_by, "
            "created_at, updated_at) VALUES (?, ?, ?, 'completed', '{}', 'test', ?, ?)",
            (job_id, provider, job_type, EARLY, EARLY),
        )
    for row_id, area in (
        ("refresh-activities", "activities"),
        ("refresh-race", "competitions"),
    ):
        db.execute(
            "INSERT INTO provider_refresh_history(id, provider, area, operation_id, "
            "trigger, started_at, phase, status) VALUES (?, ?, ?, 'op', 'manual', ?, "
            "'done', 'success')",
            (row_id, ICU, area, EARLY),
        )
    for key, value in {**INGEST_KEYS, **KEPT_KEYS}.items():
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, EARLY),
        )
    db.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES ('canonical_backfill_state', ?, ?)",
        (
            json.dumps(
                {
                    "status": "complete",
                    "counters": {ICU: {"inserted": 4}, "garmin": {"inserted": 4}},
                }
            ),
            EARLY,
        ),
    )


def _outputs(db: Any) -> None:
    db.execute(
        "INSERT INTO remote_links(entity_kind, local_id, provider, remote_id, "
        "sync_state) VALUES ('planned_unit', 'unit-1', ?, 'event-1', 'synced')",
        (ICU,),
    )
    db.execute(
        "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
        "target, course_profile, notes, intervals_event_id, created_at, updated_at) "
        "VALUES ('race-1', 'Race', '2026-12-01', 'run', 'A', '10k', '', '', '', "
        "'event-2', ?, ?)",
        (EARLY, EARLY),
    )
    db.execute(
        "INSERT INTO competition_sync_tombstones(id, intervals_event_id, created_at) "
        "VALUES ('race-0', 'event-3', ?)",
        (EARLY,),
    )


def build_v21(path: Path, *, rating_finished: bool = True) -> None:
    """Write the populated released v21 database to ``path``."""
    db = sqlite3.connect(path)
    try:
        db.executescript(FIXTURE.read_text(encoding="utf-8"))
        db.execute("PRAGMA foreign_keys = ON")
        _bundles(db)
        _athlete_data(db)
        _ingest_rows(db)
        _outputs(db)
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (RATING_STATE, json.dumps({"finished": rating_finished}), EARLY),
        )
        db.commit()
    finally:
        db.close()


def open_current(
    case: unittest.TestCase, *, rating_finished: bool = True
) -> DatabaseManager:
    """A manager over the populated database, upgraded to the current schema."""
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    path = Path(directory.name) / "intervals-coach.db"
    build_v21(path, rating_finished=rating_finished)
    manager = DatabaseManager(path, sqlite3, row_factory=row_factory, timeout=1)
    case.addCleanup(manager.close)
    with manager.unit_of_work() as db:
        migrate_schema(db)
    return manager


def dump(manager: DatabaseManager) -> list[str]:
    with manager.reader() as db:
        return [
            line for line in db.iterdump() if not line.startswith(("BEGIN", "COMMIT"))
        ]


def key_values() -> KeyValueRepository:
    return KeyValueRepository(lambda: NOW)


def kv(manager: DatabaseManager, key: str) -> str | None:
    with manager.reader() as db:
        return key_values().get(db, key)


def sessions(manager: DatabaseManager) -> dict[str, tuple[str, str | None, str | None]]:
    with manager.reader() as db:
        return {
            row["activity_id"]: (
                row["state"],
                row["merged_into"],
                row["merged_into_retained"],
            )
            for row in db.execute(
                "SELECT activity_id, state, merged_into, merged_into_retained "
                "FROM activity_sessions"
            )
        }


def feedback(manager: DatabaseManager) -> dict[str, tuple[str, str | None, str | None]]:
    with manager.reader() as db:
        return {
            row["activity_id"]: (row["notes"], row["session_id"], row["provider"])
            for row in db.execute(
                "SELECT activity_id, notes, session_id, provider FROM activity_feedback"
            )
        }


def purge(manager: DatabaseManager) -> dict[str, Any] | None:
    with manager.unit_of_work() as db:
        return run_purge(db, key_values(), now=NOW)


class IntervalsPurgeTests(unittest.TestCase):
    def test_purge_rekeys_athlete_data_and_deletes_the_ingest_store(self) -> None:
        manager = open_current(self)

        counts = purge(manager)

        assert counts is not None
        self.assertEqual(
            {key: value for key, value in counts.items() if key != "deleted"},
            {
                "activities_tombstoned": 4,
                "sessions_rebundled": 2,
                "feedback_rekeyed": 2,
                "feedback_collisions_dropped": 3,
                "feedback_lost_intervals_only": 1,
                "feedback_unresolved_kept": 1,
                "equipment_rekeyed": 1,
                "equipment_collisions_dropped": 2,
                "equipment_lost_intervals_only": 1,
                "target_snapshots_carried": 2,
                "history_entries_not_undoable": 1,
                "session_corrections_not_undoable": 1,
                "sessions_deleted": 1,
                "sessions_kept_as_tombstones": 3,
            },
        )
        self.assertEqual(counts["deleted"]["activity_records"], 4)
        self.assertEqual(counts["deleted"]["provider_records"], 5)
        self.assertEqual(counts["deleted"]["kv"], len(INGEST_KEYS))
        # Garmin and Wahoo copies survive; old ids resolve through the tombstones.
        self.assertEqual(
            sessions(manager),
            {
                "act_gar_a": ("active", None, None),
                "act_ivl_a": ("deleted", None, "act_gar_a"),
                "act_gar_b": ("active", None, None),
                "act_ivl_b": ("deleted", None, "act_gar_b"),
                "act_wah_c": ("active", None, None),
                "act_ivl_c": ("deleted", None, "act_wah_c"),
                "act_gar_x": ("active", None, None),
            },
        )
        with manager.reader() as db:
            self.assertEqual(
                canonical_store.effective_session_ids(db, ["act_ivl_a", "act_ivl_c"]),
                {"act_ivl_a": "act_gar_a", "act_ivl_c": "act_wah_c"},
            )
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(
            feedback(manager),
            {
                "act_gar_a": ("moved", "act_gar_a", None),
                "act_gar_b": ("newer moved", "act_gar_b", None),
                "act_wah_c": ("newer resident", None, None),
                "ivl-999": ("unresolved", None, ICU),
                "act_gar_x": ("untouched", "act_gar_x", None),
            },
        )

    def test_feedback_reads_on_the_surviving_session(self) -> None:
        manager = open_current(self)
        purge(manager)

        service = ActivityFeedbackService(
            manager, ActivityFeedbackRepository(lambda: NOW)
        )
        found = service.for_activity_ids(["act_gar_a", "act_ivl_a"], sessions_only=True)

        self.assertEqual(
            [(item["activity_id"], item["notes"]) for item in found],
            [("act_gar_a", "moved"), ("act_ivl_a", "moved")],
        )

    def test_equipment_targets_history_and_profile_follow_the_survivor(self) -> None:
        manager = open_current(self)
        purge(manager)

        moved = json.loads(kv(manager, "equipment_assignment:act_gar_a") or "{}")
        self.assertEqual(
            moved,
            {
                "activity_id": "act_gar_a",
                "equipment_id": "eq-1",
                "observed_at": OLD_FEEDBACK,
            },
        )
        kept = json.loads(kv(manager, "equipment_assignment:act_wah_c") or "{}")
        self.assertEqual(kept["observed_at"], NEW_FEEDBACK)
        for key in ("ivl-101", "ivl-104", "act_ivl_only"):
            self.assertIsNone(kv(manager, "equipment_assignment:" + key))
        with manager.reader() as db:
            analyses = {
                row["activity_id"]: json.loads(row["payload"])["target_snapshot"]
                for row in db.execute(
                    "SELECT activity_id, payload FROM activity_detail_analysis"
                )
            }
            self.assertEqual(analyses, {"act_gar_a": TARGETS, "act_wah_c": TARGETS})
            history = {
                row["id"]: dict(row)
                for row in db.execute("SELECT * FROM change_history")
            }
            self.assertFalse(change_history.undoable(history[FEEDBACK_HISTORY_ID]))
            self.assertTrue(change_history.undoable(history[PROFILE_HISTORY_ID]))
            self.assertFalse(change_history.undoable(history[BUNDLE_HISTORY_ID]))
            self.assertTrue(change_history.undoable(history[GARMIN_HISTORY_ID]))
            self.assertIs(
                change_history.public_view(history[FEEDBACK_HISTORY_ID])["undoable"],
                False,
            )
            with self.assertRaises(AppError) as rejected:
                HistoryUndoService._load_history(db, FEEDBACK_HISTORY_ID)
            self.assertEqual(rejected.exception.status, 400)
        # No unattended profile write: normalization ignores the old source.
        profile = json.loads(kv(manager, "profile") or "{}")
        self.assertEqual(profile["preferred_source_body"], ICU)
        self.assertEqual(normalize_profile(profile)["preferred_source_body"], "")
        self.assertIsNone(kv(manager, "equipment_assignment:gar-201"))

    def test_ingest_rows_go_and_output_ids_stay(self) -> None:
        manager = open_current(self)
        purge(manager)

        with manager.reader() as db:
            counts = intervals_row_counts(db)
            self.assertEqual(counts.pop("activity_sessions"), 3)
            self.assertEqual(counts.pop("provider_records_by_kind"), {})
            self.assertEqual(counts.pop("observations_by_metric"), {})
            self.assertEqual(set(counts.values()), {0})
            self.assertEqual(
                db.execute(
                    "SELECT provider, COUNT(*) AS n FROM activity_records "
                    "WHERE state = 'active' GROUP BY provider ORDER BY provider"
                ).fetchall(),
                [{"provider": "garmin", "n": 3}, {"provider": "wahoo", "n": 1}],
            )
            self.assertEqual(
                [
                    row["id"]
                    for row in db.execute("SELECT id FROM sync_jobs ORDER BY id")
                ],
                ["job-garmin", "job-push"],
            )
            self.assertEqual(
                [
                    row["id"]
                    for row in db.execute("SELECT id FROM provider_refresh_history")
                ],
                ["refresh-race"],
            )
            self.assertEqual(
                db.execute("SELECT provider FROM provider_sync_cursors").fetchall(),
                [{"provider": "garmin"}],
            )
            self.assertEqual(
                db.execute("SELECT DISTINCT provider FROM observations").fetchall(),
                [{"provider": "garmin"}],
            )
            self.assertEqual(
                db.execute(
                    "SELECT local_id, remote_id FROM remote_links WHERE provider = ?",
                    (ICU,),
                ).fetchall(),
                [{"local_id": "unit-1", "remote_id": "event-1"}],
            )
            self.assertEqual(
                db.execute("SELECT intervals_event_id FROM competitions").fetchone(),
                {"intervals_event_id": "event-2"},
            )
            self.assertEqual(
                db.execute(
                    "SELECT intervals_event_id FROM competition_sync_tombstones"
                ).fetchone(),
                {"intervals_event_id": "event-3"},
            )
        for key in INGEST_KEYS:
            self.assertIsNone(kv(manager, key), key)
        for key, value in KEPT_KEYS.items():
            self.assertEqual(kv(manager, key), value)
        self.assertEqual(kv(manager, "intervals_ingest_enabled"), "0")
        backfill = json.loads(kv(manager, "canonical_backfill_state") or "{}")
        self.assertEqual(backfill["counters"], {"garmin": {"inserted": 4}})

    def test_gate_waits_for_the_rating_backfill_and_runs_once(self) -> None:
        manager = open_current(self, rating_finished=False)
        before = dump(manager)

        self.assertIsNone(purge(manager))
        self.assertEqual(dump(manager), before)
        with manager.reader() as db:
            self.assertEqual(
                purge_status(db, key_values()),
                {"status": "waiting_for_rating_backfill", "version": 1},
            )
            self.assertEqual(
                summarize_intervals_purge(key_values(), db)["status"],
                "waiting_for_rating_backfill",
            )

        with manager.unit_of_work() as db:
            key_values().set(db, RATING_STATE, json.dumps({"finished": True}))
        with manager.reader() as db:
            self.assertEqual(purge_status(db, key_values())["status"], "pending")
        counts = purge(manager)
        self.assertIsNotNone(counts)
        after = dump(manager)

        # A rerun, and one after a same-build restart, changes nothing.
        self.assertIsNone(purge(manager))
        manager.close()
        restarted = DatabaseManager(manager.path, sqlite3, row_factory=row_factory)
        self.addCleanup(restarted.close)
        with restarted.unit_of_work() as db:
            migrate_schema(db)
        self.assertIsNone(purge(restarted))
        self.assertEqual(dump(restarted), after)
        with restarted.reader() as db:
            status = purge_status(db, key_values())
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["counts"], json.loads(json.dumps(counts)))

    def test_running_ingest_job_postpones_the_purge(self) -> None:
        manager = open_current(self)
        with manager.unit_of_work() as db:
            db.execute(
                "UPDATE sync_jobs SET status = 'running' WHERE id = 'job-refresh'"
            )

        self.assertIsNone(purge(manager))
        self.assertIsNone(kv(manager, intervals_purge.STATE_KEY))

    def test_diagnostics_report_unavailable_on_a_failing_read(self) -> None:
        broken = mock.Mock()
        broken.execute.side_effect = sqlite3.OperationalError("no such table")
        self.assertEqual(
            summarize_intervals_purge(key_values(), broken), {"status": "unavailable"}
        )


class IntervalsPurgeRunnerTests(unittest.TestCase):
    def runner(
        self,
        manager: DatabaseManager,
        backup: Any,
        *,
        gate: MaintenanceGate | None = None,
        lock: Any = None,
    ) -> IntervalsPurgeRunner:
        return IntervalsPurgeRunner(
            database=lambda: manager,
            key_values=key_values(),
            maintenance_gate=gate or MaintenanceGate(),
            backup=backup,
            clock=lambda: NOW,
            data_dir=lambda: manager.path.parent,
            sync_lock=lock or threading.Lock(),
            writer_wait_seconds=1,
        )

    def test_recovery_copy_is_written_before_anything_is_deleted(self) -> None:
        manager = open_current(self)
        data_dir = manager.path.parent
        service = DatabaseBackupService(
            manager,
            mock.MagicMock(),
            DatabaseBackupConfig(
                database_path=manager.path,
                data_dir=data_dir,
                maximum_bytes=100_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=60,
            ),
            mock.Mock(),
        )
        names: list[str] = []

        def backup() -> str:
            names.append(service.write_recovery_copy(BACKUP_LABEL))
            return names[-1]

        self.runner(manager, backup).run()

        (name,) = names
        self.assertTrue(name.startswith("intervals-coach.db.pre-intervals-purge-"))
        copy = sqlite3.connect(data_dir / name)
        try:
            self.assertEqual(
                copy.execute(
                    "SELECT COUNT(*) FROM activity_records WHERE provider = ?", (ICU,)
                ).fetchone()[0],
                4,
            )
        finally:
            copy.close()
        self.assertEqual(
            json.loads(kv(manager, intervals_purge.STATE_KEY) or "{}")["status"], "done"
        )
        # A restart finds the marker: no second copy, nothing changes.
        after = dump(manager)
        backup_again = mock.Mock()
        self.runner(manager, backup_again).run()
        backup_again.assert_not_called()
        self.assertEqual(dump(manager), after)

    def test_failure_mid_purge_rolls_back_and_is_not_retried(self) -> None:
        manager = open_current(self)
        before = dump(manager)
        backup = mock.Mock(return_value="copy")
        runner = self.runner(manager, backup)

        with (
            mock.patch.object(
                intervals_purge, "_delete_sessions", side_effect=RuntimeError("disk")
            ),
            self.assertLogs("intervals_coach", "ERROR") as logs,
        ):
            runner.run()
        runner.run()

        backup.assert_called_once_with()
        self.assertEqual(dump(manager), before)
        self.assertIsNone(kv(manager, intervals_purge.STATE_KEY))
        self.assertIn("intervals_purge_failed", logs.records[0].__dict__["event"])

    def test_maintenance_postpones_without_a_copy(self) -> None:
        manager = open_current(self)
        gate = MaintenanceGate()
        backup = mock.Mock()
        runner = self.runner(manager, backup, gate=gate)
        with gate.restore():
            runner.run()
        backup.assert_not_called()
        runner.run()
        backup.assert_called_once_with()


class IntervalsPurgeSafetyTests(unittest.TestCase):
    def runner(
        self, manager: DatabaseManager, backup: Any, lock: Any
    ) -> IntervalsPurgeRunner:
        return IntervalsPurgeRunner(
            database=lambda: manager,
            key_values=key_values(),
            maintenance_gate=MaintenanceGate(),
            backup=backup,
            clock=lambda: NOW,
            data_dir=lambda: manager.path.parent,
            sync_lock=lock,
            writer_wait_seconds=1,
        )

    def copy_writer(self, manager: DatabaseManager) -> mock.Mock:
        def write() -> str:
            name = f"intervals-coach.db.{BACKUP_LABEL}-20261107090000-abc"
            (manager.path.parent / name).write_bytes(b"copy")
            return name

        return mock.Mock(side_effect=write)

    def test_a_held_sync_lock_postpones_and_the_copy_is_reused(self) -> None:
        manager = open_current(self)
        lock = threading.Lock()
        backup = self.copy_writer(manager)
        runner = self.runner(manager, backup, lock)

        with lock:
            runner.run()
        self.assertIsNone(kv(manager, intervals_purge.STATE_KEY))
        runner.run()

        backup.assert_called_once_with()
        self.assertEqual(
            json.loads(kv(manager, intervals_purge.STATE_KEY) or "{}")["status"],
            "done",
        )
        self.assertFalse(lock.locked())

    def test_a_stale_running_flag_with_a_free_lock_does_not_block(self) -> None:
        manager = open_current(self)
        with manager.unit_of_work() as db:
            key_values().set(db, "sync_running", "1")
        lock = threading.Lock()

        self.runner(manager, self.copy_writer(manager), lock).run()

        self.assertEqual(
            json.loads(kv(manager, intervals_purge.STATE_KEY) or "{}")["status"],
            "done",
        )
        self.assertIsNone(kv(manager, "sync_running"))

    def test_a_restored_pre_purge_copy_is_not_purged_again(self) -> None:
        manager = open_current(self)
        backup = self.copy_writer(manager)
        self.runner(manager, backup, threading.Lock()).run()
        marker = manager.path.parent / intervals_purge.MARKER_FILE
        self.assertTrue(marker.is_file())

        # The restored copy has no database marker and every Intervals.icu row.
        manager.close()
        manager.path.unlink()
        build_v21(manager.path)
        restored = DatabaseManager(manager.path, sqlite3, row_factory=row_factory)
        self.addCleanup(restored.close)
        with restored.unit_of_work() as db:
            migrate_schema(db)
        before = dump(restored)
        again = mock.Mock()
        self.runner(restored, again, threading.Lock()).run()

        again.assert_not_called()
        self.assertEqual(dump(restored), before)
        # The restored copy keeps its ingest off: the file counts as the marker.
        switch = IntervalsIngestSwitch(
            restored,
            key_values(),
            purge_marker=lambda: purge_marker_exists(restored.path.parent),
        )
        self.assertTrue(switch.purged())
        with self.assertRaises(AppError):
            switch.save({"enabled": True})
        with restored.reader() as db:
            self.assertEqual(
                summarize_intervals_purge(key_values(), db, marker_exists=True),
                {"status": "done_restored", "version": 1},
            )

    def test_purged_ingest_cannot_be_turned_on_or_read_once(self) -> None:
        manager = open_current(self)
        switch = IntervalsIngestSwitch(manager, key_values())
        self.assertFalse(switch.purged())
        self.assertEqual(switch.save({"enabled": True})["enabled"], True)
        switch.save({"enabled": False})

        purge(manager)

        self.assertTrue(switch.purged())
        with self.assertRaises(AppError) as refused:
            switch.save({"enabled": True})
        self.assertEqual(
            (refused.exception.status, refused.exception.reason),
            (409, "intervals_ingest_purged"),
        )
        self.assertEqual(switch.save({"enabled": False})["enabled"], False)
        runtime = mock.Mock()
        service = IntervalsSyncService(
            cast(Any, mock.Mock(intervals_api_key="key")),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, runtime),
            ingest=switch,
        )
        self.assertEqual(service.sync(one_off=True), ingest_off_result())
        runtime.operation.assert_not_called()

    def test_the_marker_file_alone_refuses_ingest_and_one_off_reads(self) -> None:
        manager = open_current(self)
        (manager.path.parent / intervals_purge.MARKER_FILE).write_text("x")
        switch = IntervalsIngestSwitch(
            manager,
            key_values(),
            purge_marker=lambda: purge_marker_exists(manager.path.parent),
        )

        with self.assertRaises(AppError) as refused:
            switch.save({"enabled": True})
        self.assertEqual(refused.exception.status, 409)
        runtime = mock.Mock()
        service = IntervalsSyncService(
            cast(Any, mock.Mock(intervals_api_key="key")),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, mock.Mock()),
            cast(Any, runtime),
            ingest=switch,
        )
        self.assertEqual(service.sync(one_off=True), ingest_off_result())
        runtime.operation.assert_not_called()

    def test_a_newer_family_item_stays_where_it_is(self) -> None:
        moves = intervals_purge._plan(
            [intervals_purge._Stored("ivl-1", "act_ivl", OLD_FEEDBACK)],
            {"act_ivl": "act_gar"},
            {"act_gar": [(OLDEST, "act_gar"), (NEW_FEEDBACK, "gar-1")]},
        )
        self.assertEqual(
            (moves.moved, sorted(moves.dropped), moves.lost),
            ({}, ["act_gar", "ivl-1"], ()),
        )


class _Stage:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.stage = name
        self._calls = calls

    def run_batch(self, _db: Any) -> BatchReport:
        self._calls.append(self.stage)
        return BatchReport(items=0, done=True)

    def mark_failed(self, _db: Any) -> None:
        self._calls.append("failed:" + self.stage)


class MaintenanceStepTests(unittest.TestCase):
    def test_steps_run_between_the_canonical_backfill_and_its_follow_ups(self) -> None:
        calls: list[str] = []
        database = mock.MagicMock()

        def failing() -> None:
            calls.append("failing step")
            raise RuntimeError("step")

        worker = CanonicalBackfillWorker(
            backfill=cast(Any, _Stage("canonical", calls)),
            database=lambda: database,
            maintenance_gate=MaintenanceGate(),
            followups=(_Stage("local_load", calls),),
            maintenance_steps=(failing, lambda: calls.append("purge")),
        )

        with self.assertLogs("backend.sync.canonical_backfill_worker", "ERROR") as logs:
            worker.run_loop()

        self.assertEqual(logs.records[0].__dict__["error_class"], "RuntimeError")

        self.assertEqual(calls, ["canonical", "failing step", "purge", "local_load"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_reports_counts_and_leaves_the_copy_unchanged(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "intervals-coach.db"
        build_v21(path, rating_finished=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        report = intervals_purge_dry_run.dry_run(
            path, "", backend=sqlite3, configure=None
        )

        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name])
        self.assertTrue(report["rolled_back"])
        self.assertEqual(report["purge_state"], "waiting_for_rating_backfill")
        self.assertFalse(report["rating_backfill"]["finished"])
        self.assertEqual(report["intervals_rows"]["before"]["activity_records"], 4)
        self.assertEqual(report["intervals_rows"]["after"]["activity_records"], 0)
        self.assertEqual(report["purge"]["feedback_rekeyed"], 2)
        self.assertEqual(report["purge"]["sessions_deleted"], 1)
        self.assertEqual(report["purge"]["sessions_rebundled"], 2)
        load = report["local_load"]
        # The Intervals.icu-only ride loses its load; two bundles keep theirs on
        # the Garmin or Wahoo survivor.
        self.assertEqual((load["sessions_before"], load["sessions_after"]), (5, 4))
        self.assertEqual(
            load["sessions"],
            {"changed": 0, "removed": 1, "added": 0, "unchanged": 4, "rekeyed": 2},
        )
        self.assertEqual(load["days_changed"], 1)
        self.assertEqual(load["fitness_fatigue"]["status"], "available")
        text = json.dumps(report)
        for content in ("act_", "ivl-", "gar-", "wah-", "2026-", '"moved"', "Athlete"):
            self.assertNotIn(content, text)

    def test_cli_requires_the_password_from_the_environment(self) -> None:
        with (
            mock.patch.dict("os.environ", {"APP_PASSWORD": ""}),
            mock.patch("sys.stderr"),
        ):
            self.assertEqual(intervals_purge_dry_run.main(["copy.db"]), 2)


class RecoveryCopySizeTests(unittest.TestCase):
    def test_a_database_above_the_download_limit_is_still_copied(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        manager = DatabaseManager(
            root / "intervals-coach.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute("CREATE TABLE records (value TEXT)")
            db.execute("INSERT INTO records VALUES ('kept')")
        page_size = 4096
        # The stubbed source reports more than the 1 GB download limit.
        pages = 2_000_000_000 // page_size
        service = DatabaseBackupService(
            manager,
            mock.MagicMock(),
            DatabaseBackupConfig(
                database_path=root / "intervals-coach.db",
                data_dir=root,
                maximum_bytes=1_000_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=120,
                disk_usage=lambda _path: mock.Mock(free=10_000_000_000_000),
            ),
            mock.Mock(),
        )
        counts = {"PRAGMA page_count": pages, "PRAGMA page_size": page_size}
        original = sqlite3.Connection.execute

        class Source:
            def __init__(self, connection: Any) -> None:
                self._connection = connection

            def execute(self, sql: str, *args: Any) -> Any:
                if sql in counts:
                    return mock.Mock(fetchone=lambda: {"value": counts[sql]})
                return original(self._connection, sql, *args)

            def backup(self, *args: Any, **kwargs: Any) -> None:
                self._connection.backup(*args, **kwargs)

        reader = manager.reader

        @contextlib.contextmanager
        def oversized() -> Any:
            with reader() as connection:
                yield Source(connection)

        with mock.patch.object(manager, "reader", oversized):
            with self.assertRaises(AppError) as refused:
                service.read_bytes()
            self.assertEqual(refused.exception.status, 413)
            name = service.write_recovery_copy(BACKUP_LABEL)

        copy = sqlite3.connect(root / name)
        try:
            self.assertEqual(
                copy.execute("SELECT value FROM records").fetchone()[0], "kept"
            )
        finally:
            copy.close()


class RecoveryCopyNameTests(unittest.TestCase):
    def test_copy_keeps_the_label_and_survives_the_staging_sweep(self) -> None:
        from backend.backup.staging_sweep import remove_orphaned_staging_files

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        manager = DatabaseManager(
            root / "intervals-coach.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute("CREATE TABLE records (value TEXT)")
        service = DatabaseBackupService(
            manager,
            mock.MagicMock(),
            DatabaseBackupConfig(
                database_path=root / "intervals-coach.db",
                data_dir=root,
                maximum_bytes=1_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=60,
            ),
            mock.Mock(),
        )

        name = service.write_recovery_copy(BACKUP_LABEL)
        remove_orphaned_staging_files(root, mock.Mock())

        self.assertEqual(
            sorted(
                p.name for p in root.iterdir() if not p.name.endswith(("-wal", "-shm"))
            ),
            sorted(["intervals-coach.db", name]),
        )


if __name__ == "__main__":
    unittest.main()
