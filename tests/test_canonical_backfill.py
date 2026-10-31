"""Canonical backfill: ingest, resume, re-projection, diagnostics and the worker thread."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import time
import unittest
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.activities.session_linking import link_activity_sessions
from backend.canonical.vocabulary import ActivityLinkKind, MetricKind, ProviderId
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db import manager as manager_module
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.diagnostics.canonical_backfill import summarize_canonical_backfill
from backend.errors import AppError, DatabaseBusyError
from backend.providers import canonical_plans
from backend.providers.canonical_plans import (
    intervals_snapshot_ingest_plan,
    wahoo_ingest_plan,
)
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
)
from backend.providers.snapshot_projection import strip_intervals_activity_sections
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import (
    DEFAULT_BATCH_SIZE,
    STATE_KEY,
    BatchReport,
    CanonicalBackfill,
    _Item,
    _reprojection_work,
    _Work,
    _write_reprojection,
)
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_ingest import ingest_plan
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

NOW = "2026-09-20T08:00:00+00:00"
LATER = "2026-09-25T00:00:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"
SECRET_ID = "secret-activity-42"
INTERVALS = ProviderId.INTERVALS.value
GARMIN = ProviderId.GARMIN.value
WAHOO = ProviderId.WAHOO.value
ACTIVITY_KIND = canonical_plans.ACTIVITY_RECORD_KIND
HEALTH_KIND = canonical_plans.HEALTH_RECORD_KIND


def log_extra(record: logging.LogRecord, name: str) -> object:
    """Read a structured field that the worker passes through ``extra=``."""
    return getattr(record, name)


def load_fixture(*parts: str) -> Any:
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


def intervals_activity(identifier: str, *, day: str = "2026-09-10") -> dict[str, Any]:
    return {
        "id": identifier,
        "name": f"Ride {identifier}",
        "start_date_local": f"{day}T07:00:00",
        "type": "Ride",
    }


def intervals_snapshot(
    activities: list[dict[str, Any]], *, synced_at: str = NOW, **raw_extra: Any
) -> dict[str, Any]:
    return {
        "synced_at": synced_at,
        "upcoming_calendar": [],
        "provider_sync": {
            "calendar_window": {"start": "2026-09-21", "end": "2026-09-30"},
            "pagination": {},
        },
        "raw_provider_data": {"activities": activities, **raw_extra},
    }


def intervals_fixture_snapshot() -> dict[str, Any]:
    return intervals_snapshot(
        load_fixture("intervals", "activities.json"),
        wellness=load_fixture("intervals", "wellness.json"),
        athlete=load_fixture("intervals", "athlete.json"),
    )


def garmin_activity(identifier: int) -> dict[str, Any]:
    return {
        "activityId": identifier,
        "activityName": f"Synthetic ride {identifier}",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-09-10 07:15:00",
        "distance": 20000.0,
        "duration": 3600.0,
    }


def synthetic_weights(count: int) -> list[dict[str, Any]]:
    template = load_fixture("garmin", "weight.json")[0]
    start = date(2025, 1, 1)
    return [
        dict(template, calendarDate=(start + timedelta(days=i)).isoformat())
        for i in range(count)
    ]


def synthetic_wellness(days: int) -> list[dict[str, Any]]:
    template = load_fixture("intervals", "wellness.json")[0]
    start = date(2026, 1, 1)
    return [
        dict(template, id=(start + timedelta(days=i)).isoformat()) for i in range(days)
    ]


def garmin_payload(**sections: Any) -> dict[str, Any]:
    return {"synced_at": NOW, "provider_sync": {"pagination": {}}, **sections}


class FakeDatabase:
    """Stands in for the database in worker tests that run on another thread."""

    def unit_of_work(self) -> Any:
        return nullcontext(Mock())


class BackfillFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.manager = self.open_manager("backfill.db")

    def open_manager(self, name: str) -> DatabaseManager:
        manager = DatabaseManager(
            Path(self.temporary.name) / name, sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            initialize_schema(db)
        return manager

    def make_backfill(self, batch_size: int = DEFAULT_BATCH_SIZE) -> CanonicalBackfill:
        return CanonicalBackfill(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
            batch_size=batch_size,
        )

    def insert_snapshot(
        self, manager: DatabaseManager, payload: dict[str, Any]
    ) -> None:
        with manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
                "VALUES (?, ?, ?, 0)",
                (json.dumps(payload), NOW, str(payload.get("synced_at", ""))),
            )

    def set_kv(self, manager: DatabaseManager, key: str, value: str) -> None:
        with manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def set_garmin(self, manager: DatabaseManager, payload: Any) -> None:
        with manager.unit_of_work() as db:
            GarminSnapshotWriter(self.key_values, lambda: ZONE).write(db, payload)

    def run_batch(
        self, backfill: CanonicalBackfill, manager: DatabaseManager | None = None
    ) -> BatchReport:
        with (manager or self.manager).unit_of_work() as db:
            return backfill.run_batch(db)

    def run_to_completion(
        self, backfill: CanonicalBackfill, manager: DatabaseManager | None = None
    ) -> list[BatchReport]:
        reports: list[BatchReport] = []
        for _ in range(1000):
            report = self.run_batch(backfill, manager)
            reports.append(report)
            if report.done:
                return reports
        self.fail("backfill did not finish")

    def summary(
        self, backfill: CanonicalBackfill, manager: DatabaseManager | None = None
    ) -> dict[str, Any]:
        with (manager or self.manager).reader() as db:
            return backfill.summary(db)

    def raw_state(self, manager: DatabaseManager | None = None) -> str | None:
        with (manager or self.manager).reader() as db:
            return self.key_values.get(db, STATE_KEY)

    def state(self, manager: DatabaseManager | None = None) -> dict[str, Any]:
        raw = self.raw_state(manager)
        self.assertIsNotNone(raw)
        return json.loads(str(raw))

    def rows(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        manager: DatabaseManager | None = None,
    ) -> list[dict[str, Any]]:
        with (manager or self.manager).reader() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def count(self, table: str, manager: DatabaseManager | None = None) -> int:
        return int(self.rows(f"SELECT COUNT(*) AS n FROM {table}", (), manager)[0]["n"])

    def canonical_snapshot(
        self, manager: DatabaseManager | None = None
    ) -> dict[str, list[str]]:
        """Canonical rows without generated ids and without the re-projection version."""
        tables = (
            "provider_records",
            "activity_records",
            "activity_sessions",
            "observations",
        )
        dropped = {"id", "activity_id", "mapped_version"}
        return {
            table: sorted(
                json.dumps(
                    {key: value for key, value in row.items() if key not in dropped},
                    sort_keys=True,
                )
                for row in self.rows(f"SELECT * FROM {table}", (), manager)
            )
            for table in tables
        }

    def write_dual_write_activity(
        self, manager: DatabaseManager, identifier: str, *, fetched_at: str
    ) -> None:
        """Write one activity and its raw record the way the live dual-write does."""
        plan = intervals_snapshot_ingest_plan(
            intervals_snapshot([intervals_activity(identifier)]), zone=ZONE
        )
        item = plan.activities[0]
        raw = next(
            record for record in plan.raw_records if record.record_kind == ACTIVITY_KIND
        )
        with manager.unit_of_work() as db:
            canonical_store.upsert_provider_record(
                db,
                provider=INTERVALS,
                record_kind=raw.record_kind,
                source_record_id=raw.source_record_id,
                payload={"newer": True},
                mapper_version=raw.mapper_version,
                fetched_at=fetched_at,
                now=fetched_at,
            )
            canonical_store.upsert_activity_record(
                db,
                item.record,
                local_date=item.local_date,
                mapper_version=item.mapper_version,
                fetched_at=fetched_at,
                now=fetched_at,
            )


class PopulatedBackfillTests(BackfillFixture):
    def test_populated_backfill_writes_canonical_rows_and_a_second_run_writes_nothing(
        self,
    ) -> None:
        self.insert_snapshot(self.manager, intervals_fixture_snapshot())
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity("900")], synced_at=LATER),
        )
        self.set_garmin(
            self.manager,
            garmin_payload(
                activities=[garmin_activity(1), garmin_activity(2)],
                weight=synthetic_weights(2),
            ),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        summary = self.summary(backfill)
        self.assertEqual(summary["status"], "complete")
        # Only the newest snapshot inserts activities. Its one activity is kept, and all
        # five older fixture activities are superseded. Garmin's two activities are kept.
        self.assertEqual(self.count("activity_records"), 1 + 2)
        self.assertEqual(self.count("activity_sessions"), 1 + 2)
        self.assertEqual(summary["providers"][INTERVALS]["superseded"], 5)
        self.assertEqual(
            sum(
                counters["sessions_created"]
                for counters in summary["providers"].values()
            ),
            1,
        )
        self.assertEqual(summary["providers"][INTERVALS]["skipped_invalid"], 0)
        self.assertEqual(
            self.state()["versions"], canonical_plans.current_mapper_versions()
        )

        before_state = self.raw_state()
        sessions = self.rows(
            "SELECT activity_id FROM activity_sessions ORDER BY activity_id"
        )
        report = self.run_batch(backfill)
        self.assertEqual(report, BatchReport(items=0, done=True))
        self.assertEqual(self.raw_state(), before_state)
        self.assertEqual(
            self.rows("SELECT activity_id FROM activity_sessions ORDER BY activity_id"),
            sessions,
        )

    def test_stripped_newest_snapshot_does_not_supersede_the_full_one(self) -> None:
        full = intervals_fixture_snapshot()
        self.insert_snapshot(self.manager, full)
        self.insert_snapshot(
            self.manager,
            strip_intervals_activity_sections({**full, "synced_at": LATER}),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        # The five activities come from the older, full snapshot: the stripped one
        # is the newest row but lists none, so it is neither the activity source
        # nor a reason to supersede the full snapshot.
        self.assertEqual(self.count("activity_records"), 5)
        self.assertEqual(counters["superseded"], 0)
        self.assertEqual(counters["skipped_invalid"], 0)
        self.assertEqual(
            self.rows("SELECT state FROM activity_records GROUP BY state"),
            [{"state": "active"}],
        )

    def test_stripped_snapshot_without_a_raw_block_is_not_skipped_invalid(
        self,
    ) -> None:
        stripped = strip_intervals_activity_sections(
            intervals_snapshot([intervals_activity("7")])
        )
        stripped.pop("raw_provider_data", None)
        self.write_dual_write_activity(self.manager, "7", fetched_at=LATER)
        self.insert_snapshot(self.manager, stripped)
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        self.assertEqual(counters["skipped_invalid"], 0)
        self.assertEqual(counters["inserted"], 0)
        # A stripped snapshot is never a deletion source: the backfill keeps the row.
        self.assertEqual(
            self.rows("SELECT state FROM activity_records"), [{"state": "active"}]
        )

    def test_pending_summary_before_any_run_has_zero_counters(self) -> None:
        backfill = self.make_backfill()
        summary = self.summary(backfill)
        self.assertEqual(summary["status"], "pending")
        self.assertEqual(summary["batches"], 0)
        self.assertEqual(summary["unresolved_feedback"], 0)
        self.assertEqual(set(summary["providers"]), {INTERVALS, GARMIN})
        self.assertTrue(
            all(
                value == 0
                for counters in summary["providers"].values()
                for value in counters.values()
            )
        )

    def test_newer_dual_write_row_is_not_overwritten(self) -> None:
        self.write_dual_write_activity(self.manager, "7", fetched_at=LATER)
        self.insert_snapshot(
            self.manager, intervals_snapshot([intervals_activity("7")])
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        self.assertEqual(counters["inserted"], 0)
        self.assertEqual(counters["already_present"], 2)
        self.assertEqual(counters["sessions_created"], 0)
        self.assertEqual(
            self.rows("SELECT fetched_at FROM activity_records"),
            [{"fetched_at": LATER}],
        )
        self.assertEqual(
            self.rows("SELECT payload FROM provider_records")[0]["payload"],
            '{"newer":true}',
        )

    def test_deleted_activity_is_not_revived(self) -> None:
        self.write_dual_write_activity(self.manager, "7", fetched_at=LATER)
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_records SET state = 'deleted'")
        self.insert_snapshot(
            self.manager, intervals_snapshot([intervals_activity("7")])
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.rows("SELECT state FROM activity_records"), [{"state": "deleted"}]
        )
        self.assertEqual(
            self.rows("SELECT state FROM activity_sessions"), [{"state": "active"}]
        )
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["already_present"], 2
        )

    def test_feedback_is_unchanged_and_unresolved_feedback_is_counted(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity("1"), intervals_activity("2")]),
        )
        with self.manager.unit_of_work() as db:
            for activity_id in ("1", "missing-9"):
                db.execute(
                    "INSERT INTO activity_feedback (activity_id, activity_name, activity_date, "
                    "notes, session_rpe, deviation_reason, created_at, updated_at) "
                    "VALUES (?, '', '', 'felt good', 6, '', ?, ?)",
                    (activity_id, NOW, NOW),
                )
        before = self.rows("SELECT * FROM activity_feedback ORDER BY activity_id")
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.rows("SELECT * FROM activity_feedback ORDER BY activity_id"), before
        )
        self.assertEqual(self.summary(backfill)["unresolved_feedback"], 1)

    def test_failed_batch_leaves_the_cursor_and_resume_matches_the_uninterrupted_run(
        self,
    ) -> None:
        payload = intervals_snapshot([intervals_activity(str(i)) for i in range(60)])
        other = self.open_manager("resumed.db")
        self.insert_snapshot(self.manager, payload)
        self.insert_snapshot(other, payload)
        uninterrupted = self.make_backfill(batch_size=100)
        self.run_to_completion(uninterrupted)

        interrupted = self.make_backfill(batch_size=100)
        self.run_batch(interrupted, other)
        with (
            patch.object(
                canonical_store,
                "insert_activity_record_if_absent",
                side_effect=RuntimeError("injected failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.run_batch(interrupted, other)
        with other.unit_of_work() as db:
            interrupted.mark_failed(db)

        failed = self.state(other)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["batches"], 1)
        self.assertEqual(failed["current"]["offset"], 100)

        resumed = self.make_backfill(batch_size=100)
        self.run_to_completion(resumed, other)
        self.assertEqual(self.state(other)["status"], "complete")
        self.assertEqual(
            self.summary(resumed, other)["providers"],
            self.summary(uninterrupted)["providers"],
        )
        self.assertEqual(self.canonical_snapshot(other), self.canonical_snapshot())

    def test_batch_size_must_stay_within_the_documented_bounds(self) -> None:
        for size in (99, 251):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.make_backfill(batch_size=size)
        for size in (100, 250):
            self.assertEqual(self.make_backfill(batch_size=size)._batch_size, size)
        self.assertEqual(DEFAULT_BATCH_SIZE, 200)

    def test_every_batch_writes_at_most_batch_size_items(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity(str(i)) for i in range(60)]),
        )
        reports = self.run_to_completion(self.make_backfill(batch_size=100))
        self.assertGreater(len(reports), 2)
        self.assertTrue(all(report.items <= 100 for report in reports))

    def test_batch_boundaries_inside_one_large_snapshot_do_not_change_the_rows(
        self,
    ) -> None:
        payload = intervals_snapshot([intervals_activity(str(i)) for i in range(250)])
        other = self.open_manager("large.db")
        self.insert_snapshot(self.manager, payload)
        self.insert_snapshot(other, payload)
        small = self.make_backfill(batch_size=100)
        small_reports = self.run_to_completion(small)
        large = self.make_backfill(batch_size=250)
        large_reports = self.run_to_completion(large, other)

        self.assertGreater(len(small_reports), len(large_reports))
        self.assertTrue(all(report.items <= 100 for report in small_reports))
        self.assertEqual(
            self.summary(small)["providers"], self.summary(large, other)["providers"]
        )
        self.assertEqual(self.canonical_snapshot(), self.canonical_snapshot(other))
        counters = self.summary(small)["providers"][INTERVALS]
        self.assertEqual(counters["duplicates"], 0)
        self.assertEqual(counters["already_present"], 0)
        self.assertEqual(counters["sessions_created"], 250)

    def test_snapshots_and_payloads_without_mapper_input_are_skipped_invalid(
        self,
    ) -> None:
        self.insert_snapshot(
            self.manager, {"synced_at": NOW, "recent_activities": [{"id": "x"}]}
        )
        self.insert_snapshot(
            self.manager,
            {"raw_provider_data": {"activities": [intervals_activity("1")]}},
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["skipped_invalid"], 2)
        self.assertEqual(self.count("activity_records"), 0)

    def test_duplicates_within_one_source_are_counted_once(self) -> None:
        wellness = load_fixture("intervals", "wellness.json")
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [intervals_activity("1"), intervals_activity("1")],
                wellness=wellness + [wellness[0]],
            ),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        self.assertGreaterEqual(counters["duplicates"], 1)
        self.assertEqual(self.count("activity_records"), 1)

    def test_snapshot_removed_mid_run_is_finished_as_empty(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity(str(i)) for i in range(60)]),
        )
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [intervals_activity(str(i)) for i in range(100, 160)], synced_at=LATER
            ),
        )
        backfill = self.make_backfill(batch_size=100)
        self.run_batch(backfill)
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM snapshots WHERE id = 2")
        self.run_to_completion(backfill)

        # The newest snapshot was removed after its first batch. The older snapshot cannot
        # take its place as authority, so its activities are superseded rather than revived.
        self.assertEqual(self.count("activity_records"), 40)
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["superseded"], 60
        )
        self.assertEqual(self.state()["status"], "complete")


class SupersessionTests(BackfillFixture):
    """Only the newest snapshot may insert activities; older snapshots never do."""

    def activity_ids(self, manager: DatabaseManager | None = None) -> list[str]:
        rows = self.rows(
            "SELECT provider_activity_id FROM activity_records ORDER BY provider_activity_id",
            (),
            manager,
        )
        return [str(row["provider_activity_id"]) for row in rows]

    def raw_activity_ids(self, manager: DatabaseManager | None = None) -> list[str]:
        rows = self.rows(
            "SELECT source_record_id FROM provider_records WHERE record_kind = ? "
            "ORDER BY source_record_id",
            (ACTIVITY_KIND,),
            manager,
        )
        return [str(row["source_record_id"]) for row in rows]

    def test_older_activities_are_superseded_whatever_their_date(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [
                    intervals_activity("early", day="2026-09-01"),
                    intervals_activity("gone-same-day", day="2026-09-10"),
                    intervals_activity("gone-later", day="2026-09-15"),
                ]
            ),
        )
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [
                    intervals_activity("kept-first", day="2026-09-10"),
                    intervals_activity("kept-last", day="2026-09-20"),
                ],
                synced_at=LATER,
            ),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        self.assertEqual(self.activity_ids(), ["kept-first", "kept-last"])
        self.assertEqual(self.raw_activity_ids(), ["kept-first", "kept-last"])
        # The early activity lies before the newest snapshot's earliest one. It is still
        # superseded, because only the newest snapshot may insert activities.
        self.assertEqual(counters["superseded"], 3)
        self.assertEqual(counters["already_present"], 0)
        self.assertEqual(counters["sessions_created"], 2)

    def test_older_snapshot_still_inserts_wellness_and_observations(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [intervals_activity("gone")], wellness=synthetic_wellness(2)
            ),
        )
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity("kept")], synced_at=LATER),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][INTERVALS]
        self.assertEqual(self.activity_ids(), ["kept"])
        self.assertEqual(counters["superseded"], 1)
        self.assertGreater(counters["inserted"], 0)
        # The only observations come from the older snapshot's wellness.
        self.assertGreater(self.count("observations"), 0)

    def test_abort_and_resume_across_older_writes_matches_the_uninterrupted_run(
        self,
    ) -> None:
        older = intervals_snapshot(
            [intervals_activity(f"old-{i}", day="2026-09-01") for i in range(60)],
            wellness=synthetic_wellness(40),
        )
        newest = intervals_snapshot(
            [intervals_activity("kept", day="2026-09-10")], synced_at=LATER
        )
        other = self.open_manager("resumed.db")
        for manager in (self.manager, other):
            self.insert_snapshot(manager, older)
            self.insert_snapshot(manager, newest)
        uninterrupted = self.make_backfill(batch_size=100)
        # The older snapshot's wellness rows span several batches.
        self.assertGreater(len(self.run_to_completion(uninterrupted)), 3)

        interrupted = self.make_backfill(batch_size=100)
        armed = {"on": False}

        def failing(write: Callable[..., Any]) -> Callable[..., Any]:
            def guarded(*args: Any, **kwargs: Any) -> Any:
                if armed["on"]:
                    raise RuntimeError("injected failure")
                return write(*args, **kwargs)

            return guarded

        with (
            patch.object(
                canonical_store,
                "insert_provider_record_if_absent",
                side_effect=failing(canonical_store.insert_provider_record_if_absent),
            ),
            patch.object(
                canonical_store,
                "insert_observation_if_absent",
                side_effect=failing(canonical_store.insert_observation_if_absent),
            ),
        ):
            self.run_batch(interrupted, other)
            self.run_batch(interrupted, other)
            # The third batch fails on its first write, so nothing in it is committed.
            armed["on"] = True
            with self.assertRaises(RuntimeError):
                self.run_batch(interrupted, other)
        with other.unit_of_work() as db:
            interrupted.mark_failed(db)

        failed = self.state(other)
        self.assertEqual(failed["status"], "failed")
        # The older snapshot has not finished, so its superseded count is not added yet.
        self.assertEqual(failed["counters"][INTERVALS]["superseded"], 0)

        resumed = self.make_backfill(batch_size=100)
        self.run_to_completion(resumed, other)
        self.assertEqual(self.state(other)["status"], "complete")
        self.assertEqual(
            self.summary(resumed, other)["providers"],
            self.summary(uninterrupted)["providers"],
        )
        self.assertEqual(self.canonical_snapshot(other), self.canonical_snapshot())
        self.assertEqual(
            self.summary(uninterrupted)["providers"][INTERVALS]["superseded"], 60
        )
        self.assertEqual(self.activity_ids(), ["kept"])
        self.assertEqual(self.activity_ids(other), ["kept"])


class ReprojectionTests(BackfillFixture):
    def populate(self) -> CanonicalBackfill:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity(str(i)) for i in range(3)]),
        )
        self.set_garmin(
            self.manager,
            garmin_payload(activities=[garmin_activity(1), garmin_activity(2)]),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        return backfill

    def bumped_activity_version(self) -> dict[tuple[str, str], int]:
        key = (INTERVALS, ACTIVITY_KIND)
        return {key: canonical_plans._MAPPER_VERSIONS[key] + 1}

    def test_previous_garmin_health_projection_repairs_scaled_pace_and_missing_ftp(
        self,
    ) -> None:
        plan = canonical_plans.garmin_ingest_plan(
            garmin_payload(
                running_threshold={
                    "speed_and_heart_rate": {"speed": 0.35833233, "heartRate": 161}
                },
                cycling_ftp={
                    "calendarDate": "2026-10-03T13:38:07.0",
                    "functionalThresholdPower": 306,
                },
            ),
            zone=ZONE,
        )
        current = canonical_plans.GARMIN_HEALTH_VERSION
        # Version 5 kept the scaled speed as m/s and rejected the FTP timestamp.
        old_observations = tuple(
            replace(
                item,
                mapper_version=5,
                observation=(
                    replace(
                        item.observation,
                        value=replace(item.observation.value, value=0.35833233),
                    )
                    if item.observation.kind is MetricKind.THRESHOLD_PACE
                    else item.observation
                ),
            )
            for item in plan.observations
            if item.observation.kind is not MetricKind.FTP
        )
        old_plan = replace(
            plan,
            raw_records=tuple(
                replace(row, mapper_version=5) for row in plan.raw_records
            ),
            observations=old_observations,
        )
        with self.manager.unit_of_work() as db:
            ingest_plan(
                db,
                old_plan,
                retrieved_at=canonical_plans.garmin_payload_retrieved_at(
                    garmin_payload(), zone=ZONE
                )
                or self.fail("retrieval time"),
                deletion_window=None,
                zone=ZONE,
            )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        rows = self.rows(
            "SELECT metric, value, mapper_version FROM observations ORDER BY metric"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {row["metric"]: row["value"] for row in rows},
            {"ftp": 306.0, "threshold_hr": 161.0, "threshold_pace": 3.5833233},
        )
        self.assertEqual({row["mapper_version"] for row in rows}, {current})
        self.run_to_completion(backfill)
        self.assertEqual(
            self.rows(
                "SELECT metric, value, mapper_version FROM observations ORDER BY metric"
            ),
            rows,
        )

    def test_garmin_version_eight_reprojects_the_training_effect_label(self) -> None:
        # #1416: rows mapped by version 7 carry no training-effect label. The
        # stored raw row already holds the merged dedicated training-load values,
        # so the version bump re-projects the label from it.
        activity = {
            **garmin_activity(1),
            "trainingEffectLabel": "tempo",
            "activityTrainingLoad": 55.0,
        }
        self.set_garmin(
            self.manager,
            garmin_payload(
                activities=[activity],
                training_load_activities=[
                    {"activityId": 1, "trainingEffectLabel": "VO2_MAX"}
                ],
            ),
        )
        backfill = self.make_backfill()
        with patch.dict(canonical_plans._MAPPER_VERSIONS, {(GARMIN, ACTIVITY_KIND): 7}):
            self.run_to_completion(backfill)
        with self.manager.unit_of_work() as db:
            # What version 7 stored: the details without the label.
            db.execute(
                "UPDATE activity_records SET details = '{}', mapper_version = 7 "
                "WHERE provider = ?",
                (GARMIN,),
            )
            db.execute(
                "UPDATE provider_records SET mapped_version = 7 "
                "WHERE provider = ? AND record_kind = ?",
                (GARMIN, ACTIVITY_KIND),
            )

        self.run_to_completion(backfill)

        rows = self.rows(
            "SELECT details, load, mapper_version FROM activity_records "
            "WHERE provider = ?",
            (GARMIN,),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            json.loads(rows[0]["details"])["training_effect_label"], "VO2_MAX"
        )
        self.assertEqual(rows[0]["load"], 55.0)
        self.assertEqual(
            rows[0]["mapper_version"],
            canonical_plans._MAPPER_VERSIONS[(GARMIN, ACTIVITY_KIND)],
        )
        self.assertEqual(self.summary(backfill)["providers"][GARMIN]["reprojected"], 1)

    def test_higher_version_reprojects_only_that_record_kind(self) -> None:
        backfill = self.populate()
        bumped = self.bumped_activity_version()
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            self.run_to_completion(backfill)
            summary = self.summary(backfill)
            self.assertEqual(summary["providers"][INTERVALS]["reprojected"], 3)
            self.assertEqual(summary["providers"][GARMIN]["reprojected"], 0)
            versions = self.rows(
                "SELECT mapped_version FROM provider_records WHERE provider = ? AND record_kind = ?",
                (INTERVALS, ACTIVITY_KIND),
            )
            self.assertEqual(
                {row["mapped_version"] for row in versions},
                {bumped[(INTERVALS, ACTIVITY_KIND)]},
            )
            self.assertEqual(
                self.state()["versions"], canonical_plans.current_mapper_versions()
            )

        self.run_to_completion(backfill)
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["reprojected"], 3
        )

    def test_live_ingested_wahoo_rows_reproject_into_an_on_demand_counter_bucket(
        self,
    ) -> None:
        # Wahoo is ingested live and is not backfilled, so its counters bucket
        # does not exist until a bumped Wahoo mapper re-projects its raw rows.
        payload = {
            "synced_at": NOW,
            "workouts": [
                {"id": 7, "starts": "2026-09-19T06:00:00Z", "workout_type_id": 1}
            ],
        }
        plan = wahoo_ingest_plan(payload, zone=ZONE)
        with self.manager.unit_of_work() as db:
            ingest_plan(
                db,
                plan,
                retrieved_at=canonical_plans.wahoo_payload_retrieved_at(
                    payload, zone=ZONE
                )
                or self.fail("retrieval time"),
                deletion_window=None,
                zone=ZONE,
            )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        self.assertNotIn(WAHOO, self.summary(backfill)["providers"])

        key = (WAHOO, ACTIVITY_KIND)
        bumped = {key: canonical_plans._MAPPER_VERSIONS[key] + 1}
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            self.run_to_completion(backfill)
            providers = self.summary(backfill)["providers"]

        self.assertEqual(providers[WAHOO]["reprojected"], 1)
        self.assertEqual(providers[WAHOO]["retired"], 0)
        self.assertEqual(providers[INTERVALS]["reprojected"], 0)
        self.assertEqual(providers[GARMIN]["reprojected"], 0)
        self.assertEqual(self.count("activity_records"), 1)

    def test_comma_decimal_wellness_stored_at_the_previous_version_is_reprojected(
        self,
    ) -> None:
        # The previous mapper rejected "80,4", so its stored row has no weight yet.
        current = canonical_plans.current_mapper_versions()[
            f"{INTERVALS}.{canonical_plans.WELLNESS_RECORD_KIND}"
        ]
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_provider_record(
                db,
                provider=INTERVALS,
                record_kind=canonical_plans.WELLNESS_RECORD_KIND,
                source_record_id="2026-10-08",
                payload={"id": "2026-10-08", "weight": "80,4", "ctl": "58,2"},
                mapper_version=current - 1,
                fetched_at=NOW,
                now=NOW,
            )
        self.assertEqual(self.count("observations"), 0)

        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["reprojected"], 1
        )
        self.assertEqual(
            self.rows(
                "SELECT metric, value, mapper_version FROM observations ORDER BY metric"
            ),
            [
                {
                    "metric": MetricKind.CTL.value,
                    "value": 58.2,
                    "mapper_version": current,
                },
                {
                    "metric": MetricKind.WEIGHT.value,
                    "value": 80.4,
                    "mapper_version": current,
                },
            ],
        )
        self.assertEqual(
            self.rows(
                "SELECT mapped_version FROM provider_records WHERE record_kind = ?",
                (canonical_plans.WELLNESS_RECORD_KIND,),
            ),
            [{"mapped_version": current}],
        )

    def test_wellness_stored_at_the_previous_version_gains_form_and_eftp(
        self,
    ) -> None:
        current = canonical_plans.current_mapper_versions()[
            f"{INTERVALS}.{canonical_plans.WELLNESS_RECORD_KIND}"
        ]
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_provider_record(
                db,
                provider=INTERVALS,
                record_kind=canonical_plans.WELLNESS_RECORD_KIND,
                source_record_id="2026-10-08",
                payload={
                    "id": "2026-10-08",
                    "ctl": 50,
                    "atl": 40,
                    "sportInfo": [{"types": ["Ride"], "eftp": 258}],
                },
                mapper_version=current - 1,
                fetched_at=NOW,
                now=NOW,
            )

        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT metric, value, source_kind, sport, mapper_version "
                "FROM observations ORDER BY metric"
            ),
            [
                {
                    "metric": metric.value,
                    "value": value,
                    "source_kind": source_kind,
                    "sport": sport,
                    "mapper_version": current,
                }
                for metric, value, source_kind, sport in (
                    (MetricKind.ATL, 40.0, "provider_reported", None),
                    (MetricKind.CTL, 50.0, "provider_reported", None),
                    (MetricKind.EFTP, 258.0, "provider_reported", "ride"),
                    (MetricKind.FORM, 10.0, "derived", None),
                )
            ],
        )

    def test_athlete_stored_at_the_previous_version_keeps_its_first_ride_setting(
        self,
    ) -> None:
        # The previous mapper wrote both ride settings to one key and kept the last.
        current = canonical_plans.current_mapper_versions()[
            f"{INTERVALS}.{canonical_plans.ATHLETE_RECORD_KIND}"
        ]
        settings = [
            {"types": ["Ride"], "eftp": 250},
            {"types": ["VirtualRide"], "eftp": 262},
        ]
        fetched = datetime.fromisoformat(NOW)
        (stale,) = map_intervals_athlete_thresholds(
            {"sportSettings": settings[1:]},
            observed_on=date(2026, 9, 20),
            retrieved_at=fetched,
        ).records
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_provider_record(
                db,
                provider=INTERVALS,
                record_kind=canonical_plans.ATHLETE_RECORD_KIND,
                source_record_id=canonical_plans.ATHLETE_RECORD_ID,
                payload={"sportSettings": settings},
                mapper_version=current - 1,
                fetched_at=NOW,
                now=NOW,
            )
            canonical_store.upsert_observation(
                db, stale, mapper_version=current - 1, now=NOW
            )

        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.rows("SELECT metric, value, sport, mapper_version FROM observations"),
            [
                {
                    "metric": MetricKind.EFTP.value,
                    "value": 250.0,
                    "sport": "ride",
                    "mapper_version": current,
                }
            ],
        )

    def test_reprojected_activities_gain_their_maximum_heart_rate(self) -> None:
        ride = {**intervals_activity("1"), "max_heartrate": 171}
        self.insert_snapshot(self.manager, intervals_snapshot([ride]))
        self.set_garmin(
            self.manager,
            garmin_payload(activities=[{**garmin_activity(1), "maxHR": 168}]),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        with self.manager.unit_of_work() as db:
            # The state the previous activity mappers left: no maximum heart rate.
            db.execute("UPDATE activity_records SET details = '{}'")

        bumped = {
            key: canonical_plans._MAPPER_VERSIONS[key] + 1
            for key in ((INTERVALS, ACTIVITY_KIND), (GARMIN, ACTIVITY_KIND))
        }
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            self.run_to_completion(backfill)

        self.assertEqual(
            {
                row["provider"]: canonical_store.activity_max_hr(row["details"])
                for row in self.rows("SELECT provider, details FROM activity_records")
            },
            {INTERVALS: 171.0, GARMIN: 168.0},
        )

    def test_garmin_health_stored_at_the_previous_version_gains_run_power(
        self,
    ) -> None:
        current = canonical_plans.current_mapper_versions()[f"{GARMIN}.{HEALTH_KIND}"]
        section = "running_threshold"
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_provider_record(
                db,
                provider=GARMIN,
                record_kind=HEALTH_KIND,
                source_record_id=section,
                payload={section: load_fixture("garmin", f"{section}.json")},
                mapper_version=current - 1,
                fetched_at=NOW,
                now=NOW,
            )

        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(self.summary(backfill)["providers"][GARMIN]["reprojected"], 1)
        self.assertEqual(
            self.rows(
                "SELECT value, unit, mapper_version FROM observations WHERE metric = ?",
                (MetricKind.RUN_THRESHOLD_POWER.value,),
            ),
            [{"value": 290.0, "unit": "W", "mapper_version": current}],
        )

    def test_garmin_snapshot_backfill_writes_the_new_health_sections(self) -> None:
        sections = ("daily_stats", "race_predictions", "endurance_score")
        self.set_garmin(
            self.manager,
            garmin_payload(
                **{name: load_fixture("garmin", f"{name}.json") for name in sections}
            ),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            {
                row["metric"]
                for row in self.rows(
                    "SELECT metric FROM observations WHERE provider = ?", (GARMIN,)
                )
            },
            {
                kind.value
                for kind in (
                    MetricKind.STEPS,
                    MetricKind.FLOORS,
                    MetricKind.DAILY_ENERGY_TOTAL,
                    MetricKind.RACE_PREDICTION_5K,
                    MetricKind.RACE_PREDICTION_10K,
                    MetricKind.RACE_PREDICTION_HALF,
                    MetricKind.RACE_PREDICTION_FULL,
                    MetricKind.ENDURANCE_SCORE,
                )
            },
        )

    def test_deleted_raw_records_are_skipped(self) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE provider_records SET state = 'deleted' "
                "WHERE provider = ? AND record_kind = ? AND source_record_id = '1'",
                (INTERVALS, ACTIVITY_KIND),
            )
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, self.bumped_activity_version()
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["reprojected"], 2
        )
        deleted = self.rows(
            "SELECT mapped_version FROM provider_records WHERE source_record_id = '1' "
            "AND provider = ? AND record_kind = ?",
            (INTERVALS, ACTIVITY_KIND),
        )
        self.assertEqual(
            deleted[0]["mapped_version"],
            canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)],
        )

    def test_rows_without_a_mapper_are_passed_over_within_the_scan_budget(self) -> None:
        self.populate()
        with self.manager.unit_of_work() as db:
            for index in range(120):
                canonical_store.upsert_provider_record(
                    db,
                    provider=INTERVALS,
                    record_kind="legacy_kind",
                    source_record_id=str(index),
                    payload={"index": index},
                    mapper_version=1,
                    fetched_at=NOW,
                    now=NOW,
                )
        # Scan budget is batch_size: 100 cannot cover the 120 legacy rows in one batch.
        bounded = self.make_backfill(batch_size=100)
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, self.bumped_activity_version()
        ):
            first = self.run_batch(bounded)
            self.assertFalse(first.done)
            reports = self.run_to_completion(bounded)

        self.assertTrue(reports[-1].done)
        self.assertEqual(self.count("provider_records"), 3 + 2 + 120)
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS n FROM provider_records WHERE record_kind = ?",
                ("legacy_kind",),
            )[0]["n"],
            120,
        )
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS n FROM provider_records WHERE record_kind = ? "
                "AND mapped_version != 1",
                ("legacy_kind",),
            )[0]["n"],
            0,
        )
        self.assertEqual(
            self.summary(bounded)["providers"][INTERVALS]["reprojected"], 3
        )

    def test_reprojection_spans_batches_and_skips_a_row_deleted_mid_way(self) -> None:
        backfill = self.make_backfill(batch_size=100)
        self.set_garmin(
            self.manager, garmin_payload(weight=[{"weight": synthetic_weights(300)}])
        )
        self.run_to_completion(backfill)
        key = (GARMIN, HEALTH_KIND)
        version = canonical_plans._MAPPER_VERSIONS[key]

        with patch.dict(canonical_plans._MAPPER_VERSIONS, {key: version + 1}):
            first = self.run_batch(backfill)
            self.assertFalse(first.done)
            current_id = self.state()["reproject_current"]["id"]
            with self.manager.unit_of_work() as db:
                db.execute(
                    "UPDATE provider_records SET state = 'deleted' WHERE id = ?",
                    (current_id,),
                )
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT mapped_version FROM provider_records WHERE id = ?",
                (current_id,),
            ),
            [{"mapped_version": version}],
        )
        self.assertEqual(self.summary(backfill)["providers"][GARMIN]["reprojected"], 0)

    def test_reprojection_from_stored_raw_rebuilds_the_original_canonical_rows(
        self,
    ) -> None:
        snapshot = intervals_fixture_snapshot()
        # Every Intervals.icu record kind with a mapper, the power curve included.
        snapshot["cycling_power_profile"] = {
            "status": "ok",
            "start": "2026-07-01",
            "end": "2026-09-28",
            "synced_at": snapshot["synced_at"],
            "points": [
                {
                    "duration_seconds": 300,
                    "watts": 320,
                    "date": "2026-09-10",
                    "activity_id": "i1",
                    "source": "Intervals.icu gemessene Leistungskurve",
                    "status": "ok",
                }
            ],
        }
        self.insert_snapshot(self.manager, snapshot)
        self.set_garmin(
            self.manager,
            garmin_payload(
                activities=load_fixture("garmin", "activities.json"),
                weight=synthetic_weights(300),
                body_battery=load_fixture("garmin", "body_battery.json"),
            ),
        )
        backfill = self.make_backfill(batch_size=100)
        self.run_to_completion(backfill)
        with self.manager.unit_of_work() as db:
            # Backfill ingest does not link; re-projection does, so link up front.
            dates = db.execute("SELECT DISTINCT local_date FROM activity_sessions")
            link_activity_sessions(
                db,
                touched_dates={date.fromisoformat(row["local_date"]) for row in dates},
                zone=ZONE,
                now=NOW,
            )
        original = self.canonical_snapshot()

        bumped = {
            key: value + 1 for key, value in canonical_plans._MAPPER_VERSIONS.items()
        }
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            self.run_to_completion(backfill)
            for (provider, kind), version in bumped.items():
                if provider == WAHOO:
                    continue  # live-ingested; this fixture stores no Wahoo rows
                with self.subTest(provider=provider, kind=kind):
                    rows = self.rows(
                        "SELECT COUNT(*) AS n FROM provider_records WHERE provider = ? "
                        "AND record_kind = ? AND mapped_version = ?",
                        (provider, kind, version),
                    )
                    self.assertGreater(rows[0]["n"], 0)

        self.assertEqual(self.canonical_snapshot(), original)

    def test_reprojection_items_must_be_activities_or_observations(self) -> None:
        raw = canonical_plans.RawRecord(
            record_kind=ACTIVITY_KIND,
            source_record_id="7",
            payload={},
            mapper_version=1,
        )
        with self.assertRaises(TypeError):
            _write_reprojection(Mock(), _Item(raw, NOW), NOW)

    def test_raw_row_without_a_mapper_projects_nothing(self) -> None:
        row = {
            "provider": INTERVALS,
            "record_kind": "unmapped",
            "source_record_id": "7",
            "payload": "{}",
            "fetched_at": NOW,
        }

        self.assertEqual(_reprojection_work(row, ZoneInfo("UTC")), _Work())

    def plan_wrapper(self, transform: Callable[[Mapping[str, Any], Any], Any]) -> Any:
        """Patch the plan the backfill uses; the real mapper runs, then ``transform`` edits it."""
        real = canonical_plans.reprojection_plan

        def plan(raw_row: Mapping[str, Any], *, zone: Any) -> Any:
            result = real(raw_row, zone=zone)
            return None if result is None else transform(raw_row, result)

        return patch(
            "backend.sync.canonical_backfill.reprojection_plan", side_effect=plan
        )

    def drop_intervals_activity(self, identifier: str) -> Any:
        """A mapper that no longer emits one Intervals activity; its raw record is untouched."""

        def transform(row: Mapping[str, Any], result: Any) -> Any:
            owned = (row["provider"], row["record_kind"], row["source_record_id"])
            return (
                replace(result, activities=())
                if owned == (INTERVALS, ACTIVITY_KIND, identifier)
                else result
            )

        return self.plan_wrapper(transform)

    def tag_observation_versions(self) -> Any:
        """A mapper whose observations carry the version they were projected with."""

        def transform(row: Mapping[str, Any], result: Any) -> Any:
            version = canonical_plans.reprojection_mapper_version(
                row["provider"], row["record_kind"]
            )
            return replace(
                result,
                observations=tuple(
                    replace(item, mapper_version=version)
                    for item in result.observations
                ),
            )

        return self.plan_wrapper(transform)

    def tombstone_intervals_activity(self, identifier: str) -> None:
        """Delete one Intervals activity and its session, keeping its raw record active."""
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id IN "
                "(SELECT activity_id FROM activity_records WHERE provider = ? "
                "AND provider_activity_id = ?)",
                (INTERVALS, identifier),
            )
            db.execute(
                "UPDATE activity_records SET state = 'deleted' "
                "WHERE provider = ? AND provider_activity_id = ?",
                (INTERVALS, identifier),
            )

    def intervals_activity_rows(self) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT r.provider_activity_id, r.state, s.state AS session_state "
            "FROM activity_records AS r "
            "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
            "WHERE r.provider = ? ORDER BY r.provider_activity_id",
            (INTERVALS,),
        )

    def test_reprojection_links_a_garmin_walk_its_moving_time_now_matches(
        self,
    ) -> None:
        # Garmin duration is elapsed time; only the moving time matches Intervals.icu.
        walk = {
            "id": "w1",
            "type": "Walk",
            "start_date_local": "2026-09-10T07:00:00",
            "moving_time": 3620,
            "distance": 5000.0,
        }
        garmin_walk = {
            "activityId": 77,
            "activityType": {"typeKey": "walking"},
            "startTimeLocal": "2026-09-10 07:00:00",
            "duration": 4500.0,
            "movingDuration": 3600.0,
            "distance": 5000.0,
        }
        self.insert_snapshot(self.manager, intervals_snapshot([walk]))
        self.set_garmin(self.manager, garmin_payload(activities=[garmin_walk]))
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        query = (
            "SELECT r.provider, s.activity_id, s.state, s.merged_into "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id ORDER BY r.provider"
        )
        with self.manager.unit_of_work() as db:
            # The state an older Garmin mapper left: no moving time, separate sessions.
            db.execute(
                "UPDATE activity_records SET moving_duration_s = NULL WHERE provider = ?",
                (GARMIN,),
            )
            _unlink_sessions(db)
        self.assertEqual({row["state"] for row in self.rows(query)}, {"active"})
        key = (GARMIN, ACTIVITY_KIND)
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS,
            {key: canonical_plans._MAPPER_VERSIONS[key] + 1},
        ):
            self.run_to_completion(backfill)

        garmin, intervals = self.rows(query)
        self.assertEqual(
            (garmin["provider"], intervals["provider"]), (GARMIN, INTERVALS)
        )
        survivor, alias = (
            (garmin, intervals) if intervals["merged_into"] else (intervals, garmin)
        )
        self.assertEqual((survivor["state"], survivor["merged_into"]), ("active", None))
        self.assertEqual(
            (alias["state"], alias["merged_into"]),
            ("duplicate", survivor["activity_id"]),
        )
        self.assertEqual(self.summary(backfill)["providers"][GARMIN]["reprojected"], 1)

    def test_reprojection_links_a_garmin_walk_by_the_intervals_elapsed_time(
        self,
    ) -> None:
        # Garmin sends no moving time; only the Intervals.icu elapsed time matches.
        walk = {
            "id": "w1",
            "type": "Walk",
            "start_date_local": "2026-09-10T07:00:00",
            "moving_time": 2400,
            "elapsed_time": 4520,
            "distance": 5000.0,
        }
        garmin_walk = {
            "activityId": 77,
            "activityType": {"typeKey": "walking"},
            "startTimeLocal": "2026-09-10 07:00:00",
            "duration": 4500.0,
            "distance": 5000.0,
        }
        self.insert_snapshot(self.manager, intervals_snapshot([walk]))
        self.set_garmin(self.manager, garmin_payload(activities=[garmin_walk]))
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        query = (
            "SELECT r.provider, s.activity_id, s.state, s.merged_into "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id ORDER BY r.provider"
        )
        with self.manager.unit_of_work() as db:
            # The state the first Intervals.icu mapper left: no elapsed time.
            db.execute(
                "UPDATE activity_records SET details = '{}' WHERE provider = ?",
                (INTERVALS,),
            )
            _unlink_sessions(db)
        self.assertEqual({row["state"] for row in self.rows(query)}, {"active"})
        key = (INTERVALS, ACTIVITY_KIND)
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS,
            {key: canonical_plans._MAPPER_VERSIONS[key] + 1},
        ):
            self.run_to_completion(backfill)

        garmin, intervals = self.rows(query)
        survivor, alias = (
            (garmin, intervals) if intervals["merged_into"] else (intervals, garmin)
        )
        self.assertEqual((survivor["state"], survivor["merged_into"]), ("active", None))
        self.assertEqual(
            (alias["state"], alias["merged_into"]),
            ("duplicate", survivor["activity_id"]),
        )
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["reprojected"], 1
        )

    def test_reprojection_keeps_a_deleted_activity_and_its_session_deleted(
        self,
    ) -> None:
        backfill = self.populate()
        self.tombstone_intervals_activity("1")
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.intervals_activity_rows(),
            [
                {
                    "provider_activity_id": "0",
                    "state": "active",
                    "session_state": "active",
                },
                {
                    "provider_activity_id": "1",
                    "state": "deleted",
                    "session_state": "deleted",
                },
                {
                    "provider_activity_id": "2",
                    "state": "active",
                    "session_state": "active",
                },
            ],
        )
        self.assertEqual(
            self.rows(
                "SELECT DISTINCT mapped_version FROM provider_records "
                "WHERE provider = ? AND record_kind = ?",
                (INTERVALS, ACTIVITY_KIND),
            ),
            [{"mapped_version": old + 1}],
        )
        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["reprojected"], 3)
        self.assertEqual(providers[INTERVALS]["retired"], 0)

    def test_reprojection_inserts_a_missing_activity_with_a_single_link_session(
        self,
    ) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "DELETE FROM activity_records WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            )
            db.execute(
                "DELETE FROM activity_sessions WHERE primary_provider = ? "
                "AND primary_provider_activity_id = '1'",
                (INTERVALS,),
            )
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT r.state, s.state AS session_state, s.link_kind "
                "FROM activity_records AS r JOIN activity_sessions AS s "
                "ON s.activity_id = r.activity_id "
                "WHERE r.provider = ? AND r.provider_activity_id = '1'",
                (INTERVALS,),
            ),
            [
                {
                    "state": "active",
                    "session_state": "active",
                    "link_kind": ActivityLinkKind.SINGLE.value,
                }
            ],
        )

    def test_reprojection_of_an_already_current_activity_changes_nothing(self) -> None:
        backfill = self.populate()
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with self.manager.unit_of_work() as db:
            # The activity columns already equal the new projection; only the raw record is behind.
            db.execute(
                "UPDATE activity_records SET updated_at = 'marker' WHERE provider = ?",
                (INTERVALS,),
            )
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT DISTINCT updated_at FROM activity_records WHERE provider = ?",
                (INTERVALS,),
            ),
            [{"updated_at": "marker"}],
        )
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["reprojected"], 3
        )

    def test_reprojection_rewrites_a_stale_active_activity_and_its_session(
        self,
    ) -> None:
        backfill = self.populate()
        query = (
            "SELECT r.name, r.state, s.started_at, s.local_date "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id "
            "WHERE r.provider = ? AND r.provider_activity_id = '1'"
        )
        projected = self.rows(query, (INTERVALS,))
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET name = 'stale' "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            )
            db.execute(
                "UPDATE activity_sessions SET started_at = '1999-01-01T00:00:00+00:00', "
                "local_date = '1999-01-01' WHERE activity_id IN "
                "(SELECT activity_id FROM activity_records WHERE provider = ? "
                "AND provider_activity_id = '1')",
                (INTERVALS,),
            )
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(self.rows(query, (INTERVALS,)), projected)
        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["reprojected"], 3)
        self.assertEqual(providers[INTERVALS]["retired"], 0)

    def test_activity_the_new_projection_drops_is_retired_and_the_rest_stay_active(
        self,
    ) -> None:
        backfill = self.populate()
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with (
            self.drop_intervals_activity("1"),
            patch.dict(
                canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
            ),
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.intervals_activity_rows(),
            [
                {
                    "provider_activity_id": "0",
                    "state": "active",
                    "session_state": "active",
                },
                {
                    "provider_activity_id": "1",
                    "state": "invalid",
                    "session_state": "active",
                },
                {
                    "provider_activity_id": "2",
                    "state": "active",
                    "session_state": "active",
                },
            ],
        )
        self.assertEqual(
            self.rows(
                "SELECT state, mapped_version FROM provider_records "
                "WHERE provider = ? AND record_kind = ? AND source_record_id = '1'",
                (INTERVALS, ACTIVITY_KIND),
            ),
            [{"state": "active", "mapped_version": old + 1}],
        )
        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["retired"], 1)
        self.assertEqual(providers[INTERVALS]["reprojected"], 3)
        self.assertEqual(providers[GARMIN]["retired"], 0)

    def test_an_already_deleted_activity_is_not_retired_again(self) -> None:
        backfill = self.populate()
        self.tombstone_intervals_activity("1")
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with (
            self.drop_intervals_activity("1"),
            patch.dict(
                canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
            ),
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT state FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            ),
            [{"state": "deleted"}],
        )
        self.assertEqual(self.summary(backfill)["providers"][INTERVALS]["retired"], 0)

    def test_retirement_keeps_a_session_that_another_active_activity_links(
        self,
    ) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET activity_id = (SELECT activity_id FROM "
                "activity_records WHERE provider = ? AND provider_activity_id = '0') "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS, INTERVALS),
            )
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with (
            self.drop_intervals_activity("1"),
            patch.dict(
                canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
            ),
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT state FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            ),
            [{"state": "invalid"}],
        )
        self.assertEqual(
            self.rows(
                "SELECT state FROM activity_sessions WHERE activity_id = (SELECT "
                "activity_id FROM activity_records WHERE provider = ? "
                "AND provider_activity_id = '0')",
                (INTERVALS,),
            ),
            [{"state": "active"}],
        )
        self.assertEqual(self.summary(backfill)["providers"][INTERVALS]["retired"], 1)

    def test_a_dropped_activity_is_invalid_and_a_later_version_restores_it(
        self,
    ) -> None:
        backfill = self.populate()
        identity = (
            "SELECT r.activity_id, r.state, s.state AS session_state "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id "
            "WHERE r.provider = ? AND r.provider_activity_id = '1'"
        )
        before = self.rows(identity, (INTERVALS,))
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with (
            self.drop_intervals_activity("1"),
            patch.dict(
                canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
            ),
        ):
            self.run_to_completion(backfill)
        dropped = self.rows(identity, (INTERVALS,))
        self.assertEqual(
            dropped,
            [
                {
                    "activity_id": before[0]["activity_id"],
                    "state": "invalid",
                    "session_state": "active",
                }
            ],
        )

        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 2}
        ):
            self.run_to_completion(backfill)
        self.assertEqual(
            self.rows(identity, (INTERVALS,)),
            [
                {
                    "activity_id": before[0]["activity_id"],
                    "state": "active",
                    "session_state": "active",
                }
            ],
        )

    def test_a_deleted_session_leaves_its_active_activity_untouched(self) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET name = 'stale' "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            )
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id IN "
                "(SELECT activity_id FROM activity_records WHERE provider = ? "
                "AND provider_activity_id = '1')",
                (INTERVALS,),
            )
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT r.name, r.state, s.state AS session_state "
                "FROM activity_records AS r JOIN activity_sessions AS s "
                "ON s.activity_id = r.activity_id "
                "WHERE r.provider = ? AND r.provider_activity_id = '1'",
                (INTERVALS,),
            ),
            [{"name": "stale", "state": "active", "session_state": "deleted"}],
        )
        self.assertEqual(self.summary(backfill)["providers"][INTERVALS]["retired"], 0)

    def test_an_unusable_payload_marks_the_owned_activity_invalid(self) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE provider_records SET payload = '{}' "
                "WHERE provider = ? AND record_kind = ? AND source_record_id = '1'",
                (INTERVALS, ACTIVITY_KIND),
            )
        old = canonical_plans._MAPPER_VERSIONS[(INTERVALS, ACTIVITY_KIND)]
        with patch.dict(
            canonical_plans._MAPPER_VERSIONS, {(INTERVALS, ACTIVITY_KIND): old + 1}
        ):
            self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT state FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = '1'",
                (INTERVALS,),
            ),
            [{"state": "invalid"}],
        )
        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["skipped_invalid"], 1)
        self.assertEqual(providers[INTERVALS]["retired"], 1)

    def test_version_bump_during_a_partial_run_restarts_the_record_from_its_first_item(
        self,
    ) -> None:
        backfill = self.make_backfill(batch_size=100)
        self.set_garmin(
            self.manager,
            garmin_payload(
                resting_hr={"calendarDate": "2026-09-19", "restingHeartRate": 49},
                weight=[{"weight": synthetic_weights(300)}],
            ),
        )
        self.run_to_completion(backfill)
        key = (GARMIN, HEALTH_KIND)
        version = canonical_plans._MAPPER_VERSIONS[key]

        with self.tag_observation_versions():
            with patch.dict(canonical_plans._MAPPER_VERSIONS, {key: version + 1}):
                self.assertFalse(self.run_batch(backfill).done)
                self.assertGreater(self.state()["reproject_current"]["offset"], 0)
            with patch.dict(canonical_plans._MAPPER_VERSIONS, {key: version + 2}):
                self.run_to_completion(backfill)

        self.assertEqual(
            self.rows(
                "SELECT DISTINCT mapper_version FROM observations WHERE provider = ?",
                (GARMIN,),
            ),
            [{"mapper_version": version + 2}],
        )
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS n FROM provider_records WHERE provider = ? "
                "AND record_kind = ? AND mapped_version != ?",
                (GARMIN, HEALTH_KIND, version + 2),
            )[0]["n"],
            0,
        )


class DiagnosticsSummaryTests(BackfillFixture):
    def test_summary_carries_counts_and_status_only(self) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity(SECRET_ID, day="2026-09-10")]),
        )
        backfill = self.make_backfill()
        self.run_to_completion(backfill)
        with self.manager.reader() as db:
            summary = summarize_canonical_backfill(backfill, db)

        text = json.dumps(summary)
        for leaked in (SECRET_ID, f"Ride {SECRET_ID}", "2026-09-10"):
            self.assertNotIn(leaked, text)
        self.assertEqual(
            set(summary), {"status", "batches", "unresolved_feedback", "providers"}
        )
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(set(summary["providers"]), {INTERVALS, GARMIN})

    def test_unavailable_without_a_reader_or_when_the_read_fails(self) -> None:
        with self.manager.reader() as db:
            self.assertEqual(
                summarize_canonical_backfill(None, db), {"status": "unavailable"}
            )
            failing = Mock()
            failing.summary.side_effect = RuntimeError(SECRET_ID)
            result = summarize_canonical_backfill(failing, db)
            malformed = Mock()
            malformed.summary.return_value = {"status": "complete"}
            self.assertEqual(
                summarize_canonical_backfill(malformed, db), {"status": "unavailable"}
            )

        self.assertEqual(result, {"status": "unavailable"})
        self.assertNotIn(SECRET_ID, json.dumps(result))


class WorkerTests(BackfillFixture):
    def make_worker(
        self,
        backfill: Any,
        *,
        database: Any | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> CanonicalBackfillWorker:
        return CanonicalBackfillWorker(
            backfill=backfill,
            database=(lambda: database)
            if database is not None
            else (lambda: FakeDatabase()),
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            thread_factory=thread_factory,
        )

    def test_assembled_worker_runs_the_backfill_to_completion(self) -> None:
        self.insert_snapshot(
            self.manager, intervals_snapshot([intervals_activity("1")])
        )
        assembly = build_canonical_backfill(
            database=lambda: self.manager,
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            maintenance_gate=MaintenanceGate(),
            clock=lambda: NOW,
            batch_size=100,
        )
        assembly.worker.run_loop()

        self.assertEqual(self.summary(assembly.status_reader)["status"], "complete")
        self.assertEqual(self.count("activity_records"), 1)

    def test_loop_stops_between_batches_when_asked(self) -> None:
        calls: list[Any] = []
        worker: CanonicalBackfillWorker

        def run_batch(db: Any) -> BatchReport:
            calls.append(db)
            if len(calls) == 2:
                worker.stop()
            return BatchReport(items=1, done=False)

        backfill = Mock()
        backfill.run_batch.side_effect = run_batch
        worker = self.make_worker(backfill)
        worker.run_loop()

        self.assertEqual(len(calls), 2)
        backfill.mark_failed.assert_not_called()

    def test_batches_yield_the_writer_to_a_waiting_foreground_request(self) -> None:
        # At startup the backfill loops batch after batch; each batch must run
        # as a background writer so a login waiting for the writer is served
        # after the current batch instead of after the whole loop.
        batch_started = threading.Event()
        foreground_done = threading.Event()
        flags: list[bool] = []
        batches_before_foreground: list[int] = []

        def run_batch(db: Any) -> BatchReport:
            flags.append(manager_module._BACKGROUND_WRITER.get())
            batch_started.set()
            time.sleep(0.01)
            done = foreground_done.is_set() or len(flags) >= 500
            return BatchReport(items=1, done=done)

        def foreground() -> None:
            batch_started.wait(5)
            with self.manager.unit_of_work(timeout=2):
                batches_before_foreground.append(len(flags))
            foreground_done.set()

        backfill = Mock()
        backfill.run_batch.side_effect = run_batch
        worker = self.make_worker(backfill, database=self.manager)
        waiter = threading.Thread(target=foreground)
        waiter.start()
        worker.run_loop()
        waiter.join(5)

        self.assertTrue(foreground_done.is_set())
        self.assertTrue(flags and all(flags))
        self.assertLessEqual(batches_before_foreground[0], 5)
        self.assertFalse(manager_module._BACKGROUND_WRITER.get())

    def test_loop_ends_when_the_backfill_reports_done(self) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = [
            BatchReport(items=1, done=False),
            BatchReport(items=0, done=True),
        ]
        self.make_worker(backfill).run_loop()

        self.assertEqual(backfill.run_batch.call_count, 2)

    def test_maintenance_refusal_waits_and_retries(self) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = [
            AppError(503, "maintenance", reason="maintenance"),
            BatchReport(items=0, done=True),
        ]
        self.make_worker(backfill).run_loop()

        self.assertEqual(backfill.run_batch.call_count, 2)
        backfill.mark_failed.assert_not_called()

    def test_writer_contention_waits_and_retries_without_failing_the_backfill(
        self,
    ) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = [
            DatabaseBusyError("writer"),
            BatchReport(items=0, done=True),
        ]
        self.make_worker(backfill).run_loop()

        self.assertEqual(backfill.run_batch.call_count, 2)
        backfill.mark_failed.assert_not_called()

    def test_non_maintenance_app_error_fails_the_run_without_retry(self) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = AppError(500, SECRET_ID, reason="internal")
        worker = self.make_worker(backfill)
        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as logs:
            worker.run_loop()

        self.assertEqual(backfill.run_batch.call_count, 1)
        backfill.mark_failed.assert_called_once()
        self.assertEqual(log_extra(logs.records[0], "error_class"), "AppError")
        self.assertNotIn(SECRET_ID, "\n".join(logs.output))

    def test_failed_batch_is_logged_without_content_and_recorded(self) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = RuntimeError(f"{SECRET_ID} Ride")
        worker = self.make_worker(backfill)
        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as logs:
            worker.run_loop()

        self.assertEqual(backfill.run_batch.call_count, 1)
        backfill.mark_failed.assert_called_once()
        self.assertEqual(
            log_extra(logs.records[0], "event"), "canonical_backfill_failed"
        )
        self.assertEqual(log_extra(logs.records[0], "error_class"), "RuntimeError")
        self.assertNotIn(SECRET_ID, "\n".join(logs.output))

    def test_failed_status_write_is_logged_without_content(self) -> None:
        backfill = Mock()
        backfill.run_batch.side_effect = RuntimeError("first failure")
        backfill.mark_failed.side_effect = OSError(SECRET_ID)
        worker = self.make_worker(backfill)
        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as logs:
            worker.run_loop()

        self.assertEqual(
            [log_extra(record, "event") for record in logs.records],
            ["canonical_backfill_failed", "canonical_backfill_status_failed"],
        )
        self.assertEqual(log_extra(logs.records[1], "error_class"), "OSError")
        self.assertNotIn(SECRET_ID, "\n".join(logs.output))

    def test_thread_is_named_daemon_starts_once_and_joins(self) -> None:
        release = threading.Event()
        threads: list[threading.Thread] = []
        created: list[dict[str, Any]] = []

        def run_batch(db: Any) -> BatchReport:
            release.wait(5)
            return BatchReport(items=0, done=True)

        def factory(**kwargs: Any) -> threading.Thread:
            created.append(kwargs)
            thread = threading.Thread(**kwargs)
            threads.append(thread)
            return thread

        backfill = Mock()
        backfill.run_batch.side_effect = run_batch
        worker = self.make_worker(backfill, thread_factory=factory)
        worker.join(1)
        worker.start()
        worker.start()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["name"], "canonical-backfill")
        self.assertTrue(created[0]["daemon"])
        release.set()
        worker.join(5)
        self.assertFalse(threads[0].is_alive())
        worker.stop()


class FollowupStageTests(unittest.TestCase):
    """Follow-up stages run after the canonical backfill, each with its own failure record."""

    class Stage:
        def __init__(self, name, log, *, fail=False):
            self.name = name
            self.log = log
            self.fail = fail
            self.failed = False

        @property
        def stage(self):
            return self.name

        def run_batch(self, db):
            self.log.append(self.name)
            if self.fail:
                raise RuntimeError("simulated follow-up failure")
            return BatchReport(items=0, done=True)

        def mark_failed(self, db):
            self.failed = True

    class BlockedStage(Stage):
        """Holds its first batch until the test releases it."""

        def __init__(self, name, log, **kwargs):
            super().__init__(name, log, **kwargs)
            self.running = threading.Event()
            self.release = threading.Event()

        def run_batch(self, db):
            if not self.running.is_set():
                self.running.set()
                self.release.wait(5)
            return super().run_batch(db)

    def make_worker(self, canonical, followups, **kwargs):
        return CanonicalBackfillWorker(
            backfill=canonical,
            database=lambda: FakeDatabase(),
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            followups=followups,
            **kwargs,
        )

    def run_worker(self, canonical, followups):
        self.make_worker(canonical, followups).run_loop()

    def start_worker(self, canonical, followups):
        """Start the worker on its own thread; return it and every thread it created."""
        threads = []

        def factory(**kwargs):
            thread = threading.Thread(**kwargs)
            threads.append(thread)
            return thread

        worker = self.make_worker(canonical, followups, thread_factory=factory)
        self.addCleanup(worker.join, 5)
        self.addCleanup(worker.stop)
        worker.start()
        return worker, threads

    def test_start_during_a_followup_reruns_the_canonical_stage(self):
        log = []
        canonical = self.Stage("canonical", log)
        followup = self.BlockedStage("followup", log)
        worker, threads = self.start_worker(canonical, [followup])
        self.addCleanup(followup.release.set)
        self.assertTrue(followup.running.wait(5))

        # A restore lands while the follow-up runs, leaves the canonical stage
        # incomplete and calls start() on the live worker.
        worker.start()
        followup.release.set()
        worker.join(5)

        self.assertEqual(["canonical", "followup", "canonical", "followup"], log)
        self.assertEqual(1, len(threads))
        self.assertFalse(threads[0].is_alive())

    def test_start_during_a_failing_followup_retries_the_pass(self):
        log = []
        canonical = self.Stage("canonical", log)
        followup = self.BlockedStage("followup", log, fail=True)
        worker, threads = self.start_worker(canonical, [followup])
        self.addCleanup(followup.release.set)
        self.assertTrue(followup.running.wait(5))

        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as logs:
            worker.start()
            followup.release.set()
            worker.join(5)

        self.assertEqual(["canonical", "followup", "canonical", "followup"], log)
        self.assertTrue(followup.failed)
        self.assertEqual(
            ["followup", "followup"],
            [log_extra(record, "stage") for record in logs.records],
        )
        self.assertEqual(1, len(threads))

    def test_start_after_the_thread_exited_runs_one_more_pass(self):
        log = []
        canonical = self.Stage("canonical", log)
        followup = self.Stage("followup", log)
        worker, threads = self.start_worker(canonical, [followup])
        worker.join(5)
        self.assertFalse(threads[0].is_alive())
        self.assertEqual(["canonical", "followup"], log)

        worker.start()
        worker.join(5)

        self.assertEqual(["canonical", "followup", "canonical", "followup"], log)
        self.assertEqual(2, len(threads))
        self.assertFalse(threads[1].is_alive())

    def test_followups_run_after_the_canonical_backfill_in_order(self):
        log = []
        canonical = self.Stage("canonical", log)
        first = self.Stage("first", log)
        second = self.Stage("second", log)
        self.run_worker(canonical, [first, second])
        self.assertEqual(["canonical", "first", "second"], log)
        self.assertFalse(canonical.failed or first.failed or second.failed)

    def test_followup_failure_marks_only_that_followup(self):
        log = []
        canonical = self.Stage("canonical", log)
        broken = self.Stage("broken", log, fail=True)
        later = self.Stage("later", log)
        self.run_worker(canonical, [broken, later])
        self.assertTrue(broken.failed)
        self.assertFalse(canonical.failed)
        self.assertFalse(later.failed)
        self.assertNotIn("later", log)

    def test_canonical_failure_skips_the_followups(self):
        log = []
        canonical = self.Stage("canonical", log, fail=True)
        followup = self.Stage("followup", log)
        self.run_worker(canonical, [followup])
        self.assertTrue(canonical.failed)
        self.assertEqual(["canonical"], log)
        self.assertFalse(followup.failed)


if __name__ == "__main__":
    unittest.main()


def _unlink_sessions(db: Any) -> None:
    """Undo the links the first ingest made, as an older mapper left the sessions."""
    db.execute(
        "UPDATE activity_sessions SET state = 'active', merged_into = NULL "
        "WHERE state = 'duplicate'"
    )
