"""Canonical backfill: ingest, resume, re-projection, diagnostics and the worker thread."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Callable
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.diagnostics.canonical_backfill import summarize_canonical_backfill
from backend.errors import AppError
from backend.providers import canonical_plans
from backend.providers.canonical_plans import intervals_snapshot_ingest_plan
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
from backend.sync.garmin_snapshot_writer import GARMIN_SNAPSHOT_KEY

NOW = "2026-09-20T08:00:00+00:00"
LATER = "2026-09-25T00:00:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"
SECRET_ID = "secret-activity-42"
INTERVALS = ProviderId.INTERVALS.value
GARMIN = ProviderId.GARMIN.value
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
        self.set_kv(manager, GARMIN_SNAPSHOT_KEY, json.dumps(payload))

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
            3,
        )
        self.assertEqual(summary["providers"][INTERVALS]["skipped_invalid"], 0)
        self.assertGreater(summary["providers"][GARMIN]["inserted"], 0)
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

    def test_source_changed_between_batches_restarts_and_counts_existing_rows(
        self,
    ) -> None:
        self.set_garmin(
            self.manager,
            garmin_payload(activities=[garmin_activity(i) for i in range(60)]),
        )
        backfill = self.make_backfill(batch_size=100)
        self.run_batch(backfill)
        self.set_garmin(
            self.manager,
            garmin_payload(activities=[garmin_activity(i) for i in range(61)]),
        )
        self.run_to_completion(backfill)

        counters = self.summary(backfill)["providers"][GARMIN]
        self.assertEqual(self.count("activity_records"), 61)
        self.assertEqual(counters["sessions_created"], 61)
        self.assertGreater(counters["already_present"], 0)
        self.assertEqual(counters["duplicates"], 0)
        self.assertEqual(
            counters["inserted"],
            self.count("provider_records")
            + self.count("activity_records")
            + self.count("observations"),
        )

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
        self.set_kv(self.manager, GARMIN_SNAPSHOT_KEY, "[]")
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        providers = self.summary(backfill)["providers"]
        self.assertEqual(providers[INTERVALS]["skipped_invalid"], 2)
        self.assertEqual(providers[GARMIN]["skipped_invalid"], 1)
        self.assertEqual(self.count("activity_records"), 0)

    def test_garmin_payload_without_a_fetch_time_is_skipped(self) -> None:
        self.set_garmin(self.manager, {"activities": [garmin_activity(1)]})
        backfill = self.make_backfill()
        self.run_to_completion(backfill)

        self.assertEqual(
            self.summary(backfill)["providers"][GARMIN]["skipped_invalid"], 1
        )
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

    def test_removed_authority_supersedes_every_remaining_snapshot_activity(
        self,
    ) -> None:
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity("old", day="2026-09-01")]),
        )
        self.insert_snapshot(
            self.manager,
            intervals_snapshot([intervals_activity("middle", day="2026-09-10")]),
        )
        self.insert_snapshot(
            self.manager,
            intervals_snapshot(
                [intervals_activity("newest", day="2026-09-20")], synced_at=LATER
            ),
        )
        # 120 weights keep the Garmin source going past the first batch, so the newest
        # snapshot's turn has not started when it is removed.
        self.set_garmin(self.manager, garmin_payload(weight=synthetic_weights(120)))
        backfill = self.make_backfill(batch_size=100)
        self.assertFalse(self.run_batch(backfill).done)
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM snapshots WHERE id = 3")
        self.run_to_completion(backfill)

        # With the authority gone, every remaining snapshot is older and inserts nothing.
        self.assertEqual(self.activity_ids(), [])
        self.assertEqual(self.raw_activity_ids(), [])
        self.assertEqual(
            self.summary(backfill)["providers"][INTERVALS]["superseded"], 2
        )

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
            "AND record_kind = ?",
            (ACTIVITY_KIND,),
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
        self.set_garmin(self.manager, garmin_payload(weight=synthetic_weights(300)))
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
        self.insert_snapshot(self.manager, intervals_fixture_snapshot())
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
        original = self.canonical_snapshot()

        bumped = {
            key: value + 1 for key, value in canonical_plans._MAPPER_VERSIONS.items()
        }
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            self.run_to_completion(backfill)
            for (provider, kind), version in bumped.items():
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


if __name__ == "__main__":
    unittest.main()
