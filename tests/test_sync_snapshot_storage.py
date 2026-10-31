"""Snapshots are stored without the activity sections the canonical tables serve.

Temporary SQLite and a fake Intervals.icu client run the real reader, ingest,
coverage, selector and snapshot repository. No provider account is used.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

from duplicate_support import TablesServe
from support import garmin_payload_fixture, load_provider_fixture

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicate_service import DuplicateActivityService
from backend.canonical.garmin_payload import STATE_KEY as GARMIN_STATE_KEY
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND, HEALTH_RECORD_KIND
from backend.providers.snapshot_projection import (
    CANONICAL_SECTIONS_KEY,
    CANONICAL_SECTIONS_TABLES,
    intervals_snapshot_has_only_compact_rows,
    without_intervals_activities,
)
from backend.sync.canonical_backfill import STATE_KEY
from backend.sync.canonical_read_assembly import build_canonical_read
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import (
    GarminSnapshotWriter,
)
from backend.sync.intervals import IntervalsSnapshotReader, IntervalsSnapshotService
from backend.sync.performance import PerformanceRefreshService
from backend.sync.snapshot_storage import SnapshotStorage
from backend.sync.state import SyncStateRepository

ALL_DAYS = -1
EARLIEST = date(2026, 1, 1)
FIRST_DAY = date(2026, 11, 10)
SECOND_DAY = date(2026, 11, 11)
KEPT_ID = "i-act-001"
DROPPED_ID = "i-act-002"
NEW_ID = "i-act-006"
OLD_ID = "i-act-000"
UNMAPPED_ID = "i-act-099"
RAW = "raw_provider_data"
RECENT = "recent_activities"
SNAPSHOT_COUNT = "SELECT COUNT(*) AS n FROM snapshots"
ACTIVITY_STATES = (
    "SELECT provider_activity_id, state FROM activity_records "
    "ORDER BY provider_activity_id"
)
CANONICAL_TABLES = (
    "provider_records",
    "activity_records",
    "activity_sessions",
    "observations",
)
GENERATED_COLUMNS = {"id", "activity_id", "mapped_version", "merged_into"}


def _activities() -> list[dict[str, Any]]:
    return load_provider_fixture("intervals/activities.json")


def _activity(identifier: str, start: str) -> dict[str, Any]:
    return {**_activities()[0], "id": identifier, "start_date_local": start}


class FakeIntervalsApi:
    """Answers the reader's calls from fixed lists, like a provider window would."""

    def __init__(self, activities: list[dict[str, Any]]) -> None:
        self.activities = activities
        self.pagination: dict[str, dict[str, Any]] = {}

    def get_paged_collection(
        self, path: str, params: dict[str, str], name: str, **kwargs: Any
    ) -> list[Any]:
        if path.endswith("/activities"):
            return [dict(item) for item in self.activities]
        if path.endswith("/wellness"):
            return load_provider_fixture("intervals/wellness.json")
        return []

    def get(self, path: str, params: Any = None, **kwargs: Any) -> Any:
        if path.endswith("/activity-power-curves"):
            raise AppError(503, "unavailable", reason="provider_unavailable")
        return load_provider_fixture("intervals/athlete.json")


class _UtcProfile:
    def get(self) -> dict[str, Any]:
        return {"timezone": "UTC"}


class Environment:
    """One database with the real sync services wired as the composition root does."""

    def __init__(
        self, directory: str, *, tables: bool, wired: bool = True, name: str = "env"
    ) -> None:
        self.manager = DatabaseManager(
            Path(directory) / f"{name}.db", sqlite3, row_factory=row_factory
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: "2026-11-01T00:00:00+00:00")
        self.snapshot_rows = SnapshotRepository()
        self.state = SyncStateRepository(
            self.manager,
            self.key_values,
            self.snapshot_rows,
            lambda: "2026-11-01T00:00:00+00:00",
        )
        self.today = FIRST_DAY
        self.selector = build_canonical_read(
            key_values=self.key_values,
            profile=_UtcProfile(),
            compact_only=lambda db: intervals_snapshot_has_only_compact_rows(
                self.state.latest_snapshot(db)
            ),
        )
        if tables:
            with self.manager.unit_of_work() as db:
                self.key_values.set(db, STATE_KEY, json.dumps({"completed_once": True}))
        self.storage = (
            SnapshotStorage(
                self.state,
                database_manager=self.manager,
                serving=self.selector,
                rows=self.selector,
            )
            if wired
            else SnapshotStorage(self.state)
        )
        self.reconciler = Mock(
            reconcile=Mock(return_value={"imported": 0, "updated": 0, "conflicts": 0})
        )
        self.service = IntervalsSnapshotService(
            self.manager,
            self.key_values,
            self.state,
            self.reconciler,
            Mock(),
            Mock(),
            lambda value: value,
            self._local_now,
            EARLIEST,
            400,
            ALL_DAYS,
            self.storage,
        )

    def close(self) -> None:
        self.manager.close()

    def _local_now(self) -> datetime:
        return datetime.combine(self.today, time(9), tzinfo=UTC)

    def _utc_now(self) -> str:
        return f"{self.today.isoformat()}T08:00:00+00:00"

    def reader(self, activities: list[dict[str, Any]]) -> IntervalsSnapshotReader:
        return IntervalsSnapshotReader(
            Mock(intervals_athlete_id="i1"),
            FakeIntervalsApi(activities),  # type: ignore[arg-type]
            self.state,
            self._local_now,
            self._utc_now,
            EARLIEST,
            400,
            ALL_DAYS,
            35,
            35,
            self.storage,
        )

    def fetch(
        self,
        activities: list[dict[str, Any]],
        *,
        days: int,
        day: date,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        self.today = day
        return self.reader(activities).fetch_snapshot(
            activity_days=days, end_date=end_date
        )

    def sync(
        self,
        activities: list[dict[str, Any]],
        *,
        days: int,
        day: date,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        snapshot = self.fetch(activities, days=days, day=day, end_date=end_date)
        stored, _ = self.service.store_snapshot(snapshot, days, end_date)
        return stored

    def refresh_performance(self, day: date) -> dict[str, Any]:
        self.today = day
        service = PerformanceRefreshService(
            Mock(intervals_api_key="key"),
            self.manager,
            self.state,
            self.key_values,
            self.reader([]),
            Mock(),
            lambda value: value,
            Mock(),
            MagicMock(),
            MagicMock(),
            threading.Lock(),
            zone_provider=lambda: UTC,
            snapshot_storage=self.storage,
        )
        return service.refresh()

    def stored(self) -> dict[str, Any]:
        """The newest snapshot row exactly as stored."""
        with self.manager.reader() as db:
            payload = self.snapshot_rows.latest_payload(db)
        return json.loads(str(payload))

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def count(self, table: str) -> int:
        return int(self.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])

    def activity_count_column(self) -> int:
        return int(
            self.rows(
                "SELECT recent_activity_count AS n FROM snapshots ORDER BY id DESC LIMIT 1"
            )[0]["n"]
        )

    def table_activity_ids(self) -> list[str]:
        with self.manager.reader() as db:
            rows = self.selector.activity_rows(db)
        return sorted(str(row["id"]) for row in rows)

    def canonical_dump(self) -> dict[str, list[str]]:
        return {
            table: sorted(
                json.dumps(
                    {k: v for k, v in row.items() if k not in GENERATED_COLUMNS},
                    sort_keys=True,
                )
                for row in self.rows(f"SELECT * FROM {table}")
            )
            for table in CANONICAL_TABLES
        }

    def coverage(self) -> str | None:
        with self.manager.reader() as db:
            return self.key_values.get(db, "canonical_coverage:intervals")


class StorageCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environments = 0

    def environment(self, *, tables: bool, wired: bool = True) -> Environment:
        self.environments += 1
        env = Environment(
            self.temporary.name,
            tables=tables,
            wired=wired,
            name=f"env{self.environments}",
        )
        self.addCleanup(env.close)
        return env

    def assert_stripped(self, snapshot: dict[str, Any]) -> None:
        self.assertEqual(snapshot[CANONICAL_SECTIONS_KEY], CANONICAL_SECTIONS_TABLES)
        self.assertNotIn(RECENT, snapshot)
        self.assertNotIn("activities", snapshot[RAW])

    def assert_full(self, snapshot: dict[str, Any], count: int) -> None:
        self.assertNotIn(CANONICAL_SECTIONS_KEY, snapshot)
        self.assertEqual(len(snapshot[RECENT]), count)
        self.assertEqual(len(snapshot[RAW]["activities"]), count)


class WriteGateTests(StorageCase):
    def test_tables_serving_stores_a_marked_snapshot_without_activity_sections(
        self,
    ) -> None:
        env = self.environment(tables=True)
        returned = env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        stored = env.stored()
        self.assert_stripped(stored)
        # Wellness, athlete and calendar sections stay: they are read directly.
        self.assertEqual(len(stored["recent_wellness"]), 3)
        self.assertEqual(len(stored[RAW]["wellness"]), 3)
        self.assertTrue(stored["athlete"])
        self.assertIn("upcoming_calendar", stored)
        # The caller still gets the full payload, and the state version keeps its count.
        self.assert_full(returned, 5)
        self.assertEqual(env.activity_count_column(), 5)
        self.assertEqual(len(env.table_activity_ids()), 5)

    def test_legacy_state_stores_the_full_snapshot(self) -> None:
        env = self.environment(tables=False)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        self.assert_full(env.stored(), 5)
        self.assertEqual(env.activity_count_column(), 5)
        self.assertEqual(env.count("activity_records"), 5)

    def test_legacy_installation_stores_what_it_stored_without_the_gate(self) -> None:
        wired = self.environment(tables=False)
        plain = self.environment(tables=False, wired=False)
        for env in (wired, plain):
            env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
            env.sync([_activity(NEW_ID, "2026-11-09T07:00:00")], days=7, day=SECOND_DAY)

        self.assertEqual(wired.stored(), plain.stored())
        self.assertEqual(wired.canonical_dump(), plain.canonical_dump())
        self.assertEqual(wired.table_activity_ids(), plain.table_activity_ids())

    def test_ingest_and_coverage_see_the_full_payload_before_stripping(self) -> None:
        stripped = self.environment(tables=True)
        full = self.environment(tables=False)
        for env in (stripped, full):
            env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        self.assertEqual(stripped.canonical_dump(), full.canonical_dump())
        self.assertIsNotNone(stripped.coverage())
        self.assertEqual(stripped.coverage(), full.coverage())

    def test_a_row_the_mapper_rejects_keeps_the_activity_sections(self) -> None:
        env = self.environment(tables=True)
        unmapped = {**_activities()[0], "id": UNMAPPED_ID, "start_date_local": None}
        env.sync([*_activities(), unmapped], days=ALL_DAYS, day=FIRST_DAY)

        stored = env.stored()
        self.assert_full(stored, 6)
        self.assertIn(UNMAPPED_ID, [row["id"] for row in stored[RAW]["activities"]])
        self.assertNotIn(UNMAPPED_ID, env.table_activity_ids())
        # The next incremental sync merges against the full snapshot and keeps it.
        env.sync([_activity(NEW_ID, "2026-11-09T07:00:00")], days=7, day=SECOND_DAY)
        self.assert_full(env.stored(), 7)
        self.assertIn(
            UNMAPPED_ID, [row["id"] for row in env.stored()[RAW]["activities"]]
        )

    def test_a_mapped_window_strips_again_once_the_rejected_row_is_gone(self) -> None:
        env = self.environment(tables=True)
        unmapped = {**_activities()[0], "id": UNMAPPED_ID, "start_date_local": None}
        env.sync([*_activities(), unmapped], days=ALL_DAYS, day=FIRST_DAY)

        env.sync(_activities(), days=ALL_DAYS, day=SECOND_DAY)

        self.assert_stripped(env.stored())
        self.assertEqual(env.activity_count_column(), 5)

    def test_rollback_leaves_neither_the_snapshot_nor_the_canonical_rows(self) -> None:
        env = self.environment(tables=True)
        env.reconciler.reconcile.side_effect = RuntimeError("reconciliation failed")
        snapshot = env.fetch(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        with self.assertRaises(RuntimeError):
            env.service.store_snapshot(snapshot, ALL_DAYS, None)

        self.assertEqual(env.count("snapshots"), 0)
        for table in CANONICAL_TABLES:
            self.assertEqual(env.count(table), 0, table)


class MergeBaseTests(StorageCase):
    def _two_runs(self, *, tables: bool) -> tuple[Environment, dict[str, Any]]:
        env = self.environment(tables=tables)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
        merged = env.sync(
            [_activity(NEW_ID, "2026-11-09T07:00:00")], days=7, day=SECOND_DAY
        )
        return env, merged

    def test_incremental_sync_after_a_stripped_snapshot_matches_the_full_run(
        self,
    ) -> None:
        stripped_env, stripped = self._two_runs(tables=True)
        full_env, full = self._two_runs(tables=False)

        self.assertTrue(stripped["incremental"])
        self.assertEqual(
            sorted(item["id"] for item in stripped[RECENT]),
            sorted(item["id"] for item in full[RECENT]),
        )
        self.assertEqual(
            sorted(item["id"] for item in stripped[RAW]["activities"]),
            sorted(item["id"] for item in full[RAW]["activities"]),
        )
        self.assertEqual(len(stripped[RECENT]), 6)
        self.assertEqual(stripped_env.canonical_dump(), full_env.canonical_dump())
        # Nothing outside the window was deleted, invalidated or duplicated.
        states = stripped_env.rows(ACTIVITY_STATES)
        self.assertEqual(len(states), 6)
        self.assertEqual({row["state"] for row in states}, {"active"})
        self.assertEqual(len({row["provider_activity_id"] for row in states}), 6)
        self.assertEqual(stripped_env.table_activity_ids()[-1], NEW_ID)
        self.assert_stripped(stripped_env.stored())
        self.assertEqual(stripped_env.activity_count_column(), 6)
        self.assert_full(full_env.stored(), 6)
        self.assertEqual(stripped_env.coverage(), full_env.coverage())

    def test_full_sync_after_a_stripped_snapshot_deletes_like_the_full_run(
        self,
    ) -> None:
        results = []
        for tables in (True, False):
            env = self.environment(tables=tables)
            env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
            remaining = [item for item in _activities() if item["id"] != DROPPED_ID]
            merged = env.sync(remaining, days=ALL_DAYS, day=SECOND_DAY)
            results.append((env, merged))
        (stripped_env, stripped), (full_env, full) = results

        self.assertNotIn("incremental", stripped)
        self.assertEqual(stripped_env.canonical_dump(), full_env.canonical_dump())
        states = {
            row["provider_activity_id"]: row["state"]
            for row in stripped_env.rows(ACTIVITY_STATES)
        }
        self.assertEqual(states[DROPPED_ID], "deleted")
        self.assertEqual(
            {key for key, value in states.items() if value == "active"},
            {"i-act-001", "i-act-003", "i-act-004", "i-act-005"},
        )
        self.assertEqual(len(stripped[RECENT]), len(full[RECENT]))
        self.assert_stripped(stripped_env.stored())

    def test_historical_sync_merges_with_the_rows_of_a_stripped_snapshot(self) -> None:
        results = []
        for tables in (True, False):
            env = self.environment(tables=tables)
            env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
            merged = env.sync(
                [_activity(OLD_ID, "2026-01-20T07:00:00")],
                days=30,
                day=SECOND_DAY,
                end_date=date(2026, 2, 1),
            )
            results.append((env, merged))
        (stripped_env, stripped), (full_env, full) = results

        self.assertEqual(
            sorted(item["id"] for item in stripped[RAW]["activities"]),
            sorted(item["id"] for item in full[RAW]["activities"]),
        )
        self.assertEqual(len(stripped[RAW]["activities"]), 6)
        self.assertEqual(stripped_env.canonical_dump(), full_env.canonical_dump())
        self.assertEqual(
            {row["state"] for row in stripped_env.rows(ACTIVITY_STATES)}, {"active"}
        )
        # The state version keeps the count the full snapshot would have stored.
        self.assertEqual(
            stripped_env.activity_count_column(), full_env.activity_count_column()
        )

    def test_merge_base_without_tables_returns_the_stored_snapshot(self) -> None:
        env = self.environment(tables=False)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        self.assertEqual(env.storage.merge_base(), env.stored())
        self.assertIsNone(
            self.environment(tables=True).storage.merge_base(),
        )

    def test_merge_base_refuses_a_stripped_snapshot_when_tables_do_not_serve(
        self,
    ) -> None:
        env = self.environment(tables=True)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
        with env.manager.unit_of_work() as db:
            env.key_values.set(db, STATE_KEY, "{}")

        with self.assertRaises(AppError) as raised:
            env.storage.merge_base()

        self.assertEqual(raised.exception.reason, "canonical_tables_unavailable")
        self.assertEqual(env.count("snapshots"), 1)

    def test_merge_base_rebuilds_the_activity_sections_of_a_stripped_snapshot(
        self,
    ) -> None:
        env = self.environment(tables=True)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)

        base = env.storage.merge_base()

        self.assertIsNotNone(base)
        assert base is not None
        self.assertNotIn(CANONICAL_SECTIONS_KEY, base)
        self.assertEqual(len(base[RECENT]), 5)
        self.assertEqual(
            sorted(row["id"] for row in base[RAW]["activities"]),
            env.table_activity_ids(),
        )


class PerformanceRefreshTests(StorageCase):
    def test_refresh_keeps_a_stripped_snapshot_stripped_with_its_count(self) -> None:
        stripped = self.environment(tables=True)
        full = self.environment(tables=False)
        for env in (stripped, full):
            env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
            result = env.refresh_performance(SECOND_DAY)
            self.assertEqual(result["status"], "ok")

        self.assert_stripped(stripped.stored())
        self.assertEqual(stripped.activity_count_column(), 5)
        self.assertEqual(len(stripped.stored()["recent_wellness"]), 3)
        self.assert_full(full.stored(), 5)
        self.assertEqual(stripped.canonical_dump(), full.canonical_dump())
        self.assertEqual(stripped.coverage(), full.coverage())
        self.assertEqual(len(stripped.table_activity_ids()), 5)


class DuplicateDeleteTests(StorageCase):
    def test_delete_leaves_the_stripped_snapshot_untouched(self) -> None:
        env = self.environment(tables=True)
        env.sync(_activities(), days=ALL_DAYS, day=FIRST_DAY)
        stored = env.stored()
        snapshots = env.rows("SELECT id, synced_at FROM snapshots")
        service = DuplicateActivityService(
            env.manager,
            Mock(latest=Mock(return_value={})),
            lambda: "2026-11-12T00:00:00+00:00",
            Mock(),
        )

        with (
            patch(
                "backend.activities.duplicate_service.resolve_duplicate_ids",
                side_effect=lambda payload, references: payload,
            ),
            patch(
                "backend.activities.duplicate_service.validate_duplicate_delete",
                return_value=("canonical", KEPT_ID),
            ),
        ):
            result = service.delete({}, Mock())

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(env.stored(), stored)
        self.assertEqual(env.rows("SELECT id, synced_at FROM snapshots"), snapshots)
        self.assertEqual(env.activity_count_column(), 5)
        self.assertEqual(KEPT_ID not in env.table_activity_ids(), True)
        self.assertEqual(len(env.table_activity_ids()), 4)


class DuplicateEnvironmentCase(StorageCase):
    """A Wahoo ride and its Garmin copy synced through the real services."""

    WAHOO = "i-wahoo-dup"
    GARMIN = "i-garmin-dup"
    KEYS = ("canonical_id", "duplicate_id", "snapshot_synced_at")

    def inspector(self, env: Environment, serving: Any = None) -> DuplicateInspector:
        return DuplicateInspector(
            env.manager, CanonicalTableReader(), lambda: UTC, serving or env.selector
        )

    def service(self, env: Environment, inspector: DuplicateInspector):
        return DuplicateActivityService(
            env.manager, inspector, lambda: "2026-11-12T00:00:00+00:00", Mock()
        )

    def confirmation(self, inspector: DuplicateInspector) -> dict[str, Any]:
        pair = inspector.latest() or {}
        return {key: pair[key] for key in self.KEYS}


def duplicate_pair() -> list[dict[str, Any]]:
    """Return the Wahoo ride and its Garmin copy as Intervals.icu activities."""
    base = {
        **_activity(DuplicateEnvironmentCase.WAHOO, "2026-11-10T07:00:00"),
        "type": "Ride",
        "moving_time": 3600,
        "distance": 30000.0,
    }
    return [
        {**base, "source": "Wahoo"},
        {
            **base,
            "id": DuplicateEnvironmentCase.GARMIN,
            "source": "Garmin",
            "moving_time": 3580,
        },
    ]


class LegacyStateDuplicateTests(DuplicateEnvironmentCase):
    """Duplicate deletes are offered only while the canonical tables serve reads.

    Before the first completed backfill the snapshot stays the source of truth and
    a delete does not rewrite it, so the next sync would revive a deleted copy.
    """

    def legacy_environment(self) -> Environment:
        env = self.environment(tables=False)
        env.sync(duplicate_pair(), days=ALL_DAYS, day=FIRST_DAY)
        with env.manager.reader() as db:
            self.assertFalse(env.selector.serves_tables(db))
        return env

    def test_no_pair_is_offered_while_the_selector_is_legacy(self) -> None:
        env = self.legacy_environment()
        # The tables hold the pair, but they do not serve reads yet.
        self.assertEqual(
            (self.inspector(env, TablesServe()).latest() or {}).get("duplicate_id"),
            self.GARMIN,
        )
        self.assertIsNone(self.inspector(env).latest())

    def test_the_pair_is_offered_once_the_tables_serve(self) -> None:
        env = self.legacy_environment()
        with env.manager.unit_of_work() as db:
            env.key_values.set(db, STATE_KEY, json.dumps({"completed_once": True}))

        pair = self.inspector(env).latest()

        self.assertEqual((pair or {}).get("duplicate_id"), self.GARMIN)

    def test_a_confirmation_in_the_legacy_state_conflicts_without_a_remote_call(
        self,
    ) -> None:
        env = self.legacy_environment()
        confirmation = self.confirmation(self.inspector(env, TablesServe()))
        remote = Mock()

        with self.assertRaises(AppError) as raised:
            self.service(env, self.inspector(env)).delete(confirmation, remote)

        self.assertEqual(raised.exception.status, 409)
        remote.delete_activity.assert_not_called()
        state = "SELECT state FROM activity_records WHERE provider_activity_id = ?"
        self.assertEqual(env.rows(state, (self.GARMIN,))[0]["state"], "active")

    def test_a_deleted_copy_revived_by_the_next_sync_is_not_offered_again(
        self,
    ) -> None:
        env = self.legacy_environment()
        confirmation = self.confirmation(self.inspector(env, TablesServe()))
        # A confirmation issued while the tables served, executed in the legacy state.
        self.service(env, self.inspector(env, TablesServe())).delete(
            dict(confirmation), Mock()
        )
        copy = "SELECT state FROM activity_records WHERE provider_activity_id = ?"
        self.assertEqual(env.rows(copy, (self.GARMIN,))[0]["state"], "deleted")

        # The snapshot is unchanged, so the next incremental sync ingests the copy.
        env.sync(duplicate_pair(), days=ALL_DAYS, day=SECOND_DAY)
        self.assertEqual(env.rows(copy, (self.GARMIN,))[0]["state"], "active")

        inspector = self.inspector(env)
        self.assertIsNone(inspector.latest())
        remote = Mock()
        with self.assertRaises(AppError) as raised:
            self.service(env, inspector).delete(dict(confirmation), remote)
        self.assertEqual(raised.exception.status, 409)
        remote.delete_activity.assert_not_called()


class DeletedCopyMergeBaseTests(DuplicateEnvironmentCase):
    """A confirmed delete survives the next incremental sync.

    The snapshot is not rewritten by a delete. When it still carries the activity
    sections (a row the mapper rejects, or a snapshot stored before the backfill
    finished) the incremental merge must not re-add the tombstoned copy, or the
    ingest would revive it and it would be offered and deleted again.
    """

    COPY_STATE = "SELECT state FROM activity_records WHERE provider_activity_id = ?"

    def unmapped_environment(self) -> Environment:
        """Tables serve, but a rejected row keeps the activity sections in the snapshot."""
        env = self.environment(tables=True)
        unmapped = {**_activities()[0], "id": UNMAPPED_ID, "start_date_local": None}
        env.sync([*duplicate_pair(), unmapped], days=ALL_DAYS, day=FIRST_DAY)
        self.assert_full(env.stored(), 3)
        return env

    def prebackfill_environment(self) -> Environment:
        """The snapshot was stored in full before the backfill finished."""
        env = self.environment(tables=False)
        env.sync(duplicate_pair(), days=ALL_DAYS, day=FIRST_DAY)
        with env.manager.unit_of_work() as db:
            env.key_values.set(db, STATE_KEY, json.dumps({"completed_once": True}))
        return env

    def delete_copy(self, env: Environment) -> dict[str, Any]:
        inspector = self.inspector(env)
        confirmation = self.confirmation(inspector)
        remote = Mock()
        self.service(env, inspector).delete(dict(confirmation), remote)
        remote.delete_activity.assert_called_once_with(self.GARMIN)
        self.assertEqual(
            env.rows(self.COPY_STATE, (self.GARMIN,))[0]["state"], "deleted"
        )
        return confirmation

    def assert_stays_deleted(
        self, env: Environment, confirmation: dict[str, Any]
    ) -> None:
        # The provider window of the incremental sync holds only the Wahoo ride.
        wahoo = duplicate_pair()[0]
        env.sync([wahoo], days=7, day=SECOND_DAY)

        self.assertEqual(
            env.rows(self.COPY_STATE, (self.GARMIN,))[0]["state"], "deleted"
        )
        self.assertNotIn(self.GARMIN, env.table_activity_ids())
        inspector = self.inspector(env)
        self.assertIsNone(inspector.latest())
        remote = Mock()
        with self.assertRaises(AppError) as raised:
            self.service(env, inspector).delete(dict(confirmation), remote)
        self.assertEqual(raised.exception.status, 409)
        remote.delete_activity.assert_not_called()

    def test_an_unmapped_row_does_not_bring_the_deleted_copy_back(self) -> None:
        env = self.unmapped_environment()
        confirmation = self.delete_copy(env)

        self.assert_stays_deleted(env, confirmation)
        stored = env.stored()
        self.assertNotIn(self.GARMIN, [row["id"] for row in stored[RAW]["activities"]])
        self.assertNotIn(self.GARMIN, [row["id"] for row in stored[RECENT]])
        # The rejected row itself is still kept.
        self.assertIn(UNMAPPED_ID, [row["id"] for row in stored[RAW]["activities"]])

    def test_a_snapshot_stored_before_the_backfill_does_not_bring_it_back(self) -> None:
        env = self.prebackfill_environment()
        confirmation = self.delete_copy(env)

        self.assert_stays_deleted(env, confirmation)

    def test_a_copy_the_provider_still_returns_is_ingested_again(self) -> None:
        env = self.prebackfill_environment()
        self.delete_copy(env)

        # The copy still exists remotely, so a fresh fetch legitimately revives it.
        env.sync(duplicate_pair(), days=7, day=SECOND_DAY)

        self.assertEqual(
            env.rows(self.COPY_STATE, (self.GARMIN,))[0]["state"], "active"
        )

    def test_a_full_window_sync_still_tombstones_missing_activities(self) -> None:
        env = self.prebackfill_environment()

        env.sync([duplicate_pair()[0]], days=ALL_DAYS, day=SECOND_DAY)

        self.assertEqual(
            env.rows(self.COPY_STATE, (self.GARMIN,))[0]["state"], "deleted"
        )
        self.assertNotIn(self.GARMIN, env.table_activity_ids())


class WithoutActivitiesTests(unittest.TestCase):
    def test_the_given_ids_leave_both_activity_sections(self) -> None:
        snapshot = {
            "synced_at": "now",
            RECENT: [{"id": "a"}, {"id": 7}, "scalar"],
            RAW: {"activities": [{"id": "a"}, {"id": "b"}, {"id": "7"}], "athlete": {}},
        }
        original = json.dumps(snapshot, sort_keys=True)

        result = without_intervals_activities(snapshot, {"a", "7"})

        self.assertEqual(result[RECENT], ["scalar"])
        self.assertEqual(result[RAW]["activities"], [{"id": "b"}])
        self.assertEqual(result[RAW]["athlete"], {})
        self.assertEqual(json.dumps(snapshot, sort_keys=True), original)

    def test_no_ids_or_missing_sections_change_nothing(self) -> None:
        snapshot = {"synced_at": "now", RAW: {"athlete": {}}}

        self.assertEqual(without_intervals_activities(snapshot, {"a"}), snapshot)
        self.assertEqual(without_intervals_activities(snapshot, set()), snapshot)


class GarminRawRecordTests(StorageCase):
    def _writer_and_manager(self) -> tuple[GarminSnapshotWriter, Environment]:
        env = self.environment(tables=True)
        writer = GarminSnapshotWriter(env.key_values, lambda: ZoneInfo("Europe/Berlin"))
        return writer, env

    def test_garmin_write_persists_raw_records_with_the_state_value(self) -> None:
        writer, env = self._writer_and_manager()
        with env.manager.unit_of_work() as db:
            writer.write(db, garmin_payload_fixture())

        kinds = {
            row["record_kind"]
            for row in env.rows(
                "SELECT DISTINCT record_kind FROM provider_records WHERE provider='garmin'"
            )
        }
        self.assertEqual(kinds, {ACTIVITY_RECORD_KIND, HEALTH_RECORD_KIND})
        with env.manager.reader() as db:
            self.assertIsNotNone(env.key_values.get(db, GARMIN_STATE_KEY))

    def test_garmin_rollback_leaves_neither_records_nor_state_value(self) -> None:
        writer, env = self._writer_and_manager()

        with self.assertRaises(RuntimeError), env.manager.unit_of_work() as db:
            writer.write(db, garmin_payload_fixture())
            raise RuntimeError("rollback")

        self.assertEqual(env.count("provider_records"), 0)
        with env.manager.reader() as db:
            self.assertIsNone(env.key_values.get(db, GARMIN_STATE_KEY))


if __name__ == "__main__":
    unittest.main()
