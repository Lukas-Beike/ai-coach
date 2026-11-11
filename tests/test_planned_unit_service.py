"""Isolated tests for local planned-unit creation and listing."""

from __future__ import annotations

import json
import threading
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from support import temp_database

from backend import change_history
from backend.activities.hr_cap import HR_CAP_PERCENT, hr_cap
from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.db import row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.planning import planned_units
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.changes import StructuredTrainingChangeValidator
from backend.planning.intervals_orphans import find_intervals_orphans
from backend.planning.local_start import known_start
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.providers import garmin_strength_workout

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class CountingDatabaseManager:
    def __init__(self, manager):
        self.manager = manager
        self.unit_of_work_calls = 0

    def unit_of_work(self):
        self.unit_of_work_calls += 1
        return self.manager.unit_of_work()


class CommitFailingDatabaseManager:
    def __init__(self, manager):
        self.manager = manager

    @contextmanager
    def unit_of_work(self):
        with self.manager.unit_of_work() as db:
            yield db
            raise RuntimeError("commit unavailable")


class CalendarConflictFake:
    def __init__(self):
        self.calls = []
        self.results = []
        self.constraint_calls = []
        self.constraint_results = []

    def constraints(self, workout):
        self.constraint_calls.append(workout)
        return self.constraint_results

    def conflicts(self, workout, exclude_library_ids):
        self.calls.append((workout, exclude_library_ids))
        return self.results


class StaticRowDb:
    def __init__(self, row):
        self.row = row

    def execute(self, _query, _params):
        return self

    def fetchone(self):
        return self.row


class PlannedUnitServiceTests(unittest.TestCase):
    def setUp(self):
        self.manager = temp_database(self, "planned-units.db", row_factory=row_factory)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.calendar_conflicts = CalendarConflictFake()
        self.events = []
        self.service = PlannedUnitService(
            self.manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value.replace("secret", "[REDACTED]"),
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )

    @staticmethod
    def workout(**overrides):
        return {
            "date": "2026-09-21",
            "sport": "Run",
            "name": "Äußerst lockerer Lauf",
            "description": "- 30m 60% locker",
            "duration_minutes": 30,
            **overrides,
        }

    def state(self):
        with self.manager.reader() as db:
            planned = db.execute(
                "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, "
                "sync_error, sync_conflict, baseline_hash, last_synced_at, created_at, updated_at "
                "FROM planned_units"
            ).fetchall()
            history = db.execute(
                "SELECT entity_type, entity_id, action, source FROM change_history"
            ).fetchall()
            revision = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()["revision"]
        return planned, history, revision

    @unittest.skipUnless(
        garmin_strength_workout.catalogue_available(), "garminconnect is not installed"
    )
    def test_athlete_picks_the_garmin_exercise_and_it_is_remembered(self):
        self.service.create(
            self.workout(
                sport="WeightTraining",
                description="",
                strength_structure=[
                    {"name": "Kabelrudern eng", "sets": 3, "reps": 10},
                    {"name": "Face Pulls", "sets": 3, "reps": 15},
                ],
            )
        )
        listed = self.service.list(push_state=True)[0]
        self.assertEqual({"garmin": "unmapped"}, listed["push_blocked"])
        self.assertEqual([0], [item["index"] for item in listed["push_unmapped"]])
        with self.assertRaises(AppError) as raised:
            self.service.assign_garmin_exercise(
                str(self.id), 0, "V-grip Cable Row", "stale"
            )
        self.assertEqual("planning_revision_conflict", raised.exception.reason)
        for index in (5, True, "0"):
            with self.subTest(index=index), self.assertRaises(AppError):
                self.service.assign_garmin_exercise(
                    str(self.id), index, "V-grip Cable Row", listed["payload_hash"]
                )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_dirty=0 "
                "WHERE local_id=?",
                (str(self.id),),
            )
        self.service.assign_garmin_exercise(
            str(self.id), 0, "v-grip cable row", listed["payload_hash"]
        )
        planned, history, _revision = self.state()
        stored = json.loads(planned[0]["payload"])["strength_structure"][0]
        self.assertEqual("V-grip Cable Row", stored["garmin_exercise"])
        self.assertEqual("V_GRIP_CABLE_ROW", stored["garmin_pair"]["exercise"])
        # The pick changes nothing Intervals.icu carries: the sync state stays.
        self.assertEqual(
            ("synced", 0), (planned[0]["sync_state"], planned[0]["sync_dirty"])
        )
        self.assertEqual("update", history[-1]["action"])
        listed = self.service.list(push_state=True)[0]
        self.assertEqual({}, listed["push_blocked"])
        self.assertEqual([], listed["push_unmapped"])

    def test_create_normalizes_and_inserts_local_sync_state(self):
        created = self.service.create(self.workout())

        planned, history, revision = self.state()
        self.assertEqual(created["id"], str(self.id))
        self.assertEqual(created["sport"], "run")
        self.assertNotIn("type", created)
        self.assertEqual(created["duration_minutes"], 30)
        self.assertEqual(planned[0]["id"], str(self.id))
        self.assertEqual(planned[0]["local_id"], str(self.id))
        self.assertIsNone(planned[0]["external_id"])
        self.assertEqual(
            json.loads(planned[0]["payload"])["name"], "Äußerst lockerer Lauf"
        )
        self.assertIn("Äußerst lockerer Lauf", planned[0]["payload"])
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertIsNone(planned[0]["baseline_hash"])
        self.assertIsNone(planned[0]["last_synced_at"])
        self.assertEqual(planned[0]["created_at"], NOW)
        self.assertEqual(planned[0]["updated_at"], NOW)
        self.assertEqual(
            [
                (row["entity_type"], row["entity_id"], row["action"], row["source"])
                for row in history
            ],
            [("planned_unit", str(self.id), "create", "local")],
        )
        self.assertEqual(revision, 1)

    def test_insert_preserves_remote_sync_metadata_on_caller_transaction(self):
        entry = {
            **self.workout(),
            "id": str(self.id),
            "external_id": "remote-42",
        }
        with self.manager.unit_of_work() as db:
            stored = self.service.insert(
                db,
                entry,
                sync_dirty=0,
                sync_state="synced",
                sync_error="secret failure",
                baseline_hash="baseline",
                last_synced_at=NOW,
            )

        planned, history, revision = self.state()
        self.assertEqual(stored["sync_status"], "synced")
        self.assertEqual(planned[0]["sync_dirty"], 0)
        self.assertEqual(planned[0]["sync_state"], "synced")
        self.assertEqual(planned[0]["sync_error"], "[REDACTED] failure")
        self.assertEqual(planned[0]["baseline_hash"], "baseline")
        self.assertEqual(planned[0]["last_synced_at"], NOW)
        self.assertEqual(history, [])
        self.assertEqual(revision, 0)

    def test_audit_and_revision_are_written_with_the_planned_unit(self):
        with self.manager.unit_of_work() as db:
            self.service.create(self.workout(), db=db, change_source="coach")
            counts = tuple(
                db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()["COUNT(*)"]
                for table in ("planned_units", "change_history")
            )
            revision = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()["revision"]

        self.assertEqual(counts, (1, 1))
        self.assertEqual(revision, 1)
        _, history, _ = self.state()
        self.assertEqual(history[0]["source"], "coach")

    def test_revision_can_be_skipped_without_skipping_audit(self):
        self.service.create(self.workout(), bump_planning_revision=False)

        planned, history, revision = self.state()
        self.assertEqual(len(planned), 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(revision, 0)

    def test_explicit_db_does_not_open_another_unit_of_work(self):
        manager = CountingDatabaseManager(self.manager)
        service = PlannedUnitService(
            manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        with self.manager.unit_of_work() as db:
            before = manager.unit_of_work_calls
            service.create(self.workout(), db=db)
            self.assertEqual(manager.unit_of_work_calls, before)

    def test_validation_failure_does_not_persist_anything(self):
        with self.assertRaises(AppError):
            self.service.create(self.workout(sport=" "))

        self.assertEqual(self.state(), ([], [], 0))

    def test_audit_failure_rolls_back_insert_and_revision(self):
        with (
            patch(
                "backend.planning.planned_unit_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.create(self.workout())

        self.assertEqual(self.state(), ([], [], 0))

    def test_revision_failure_rolls_back_insert_and_audit(self):
        with (
            patch.object(
                self.service._planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision unavailable"),
        ):
            self.service.create(self.workout())

        self.assertEqual(self.state(), ([], [], 0))

    def test_future_only_since_reads_earlier_units_of_the_week(self):
        for index, (day, name) in enumerate(
            (
                ("2026-09-13", "Last week"),
                ("2026-09-15", "Missed Tuesday"),
                ("2026-09-20", "Today"),
            )
        ):
            self.id = uuid.UUID(f"{index + 1}2345678-1234-5678-1234-567812345678")
            self.service.create(self.workout(date=day, name=name))

        since = date(2026, 9, 14)
        widened = self.service.list(future_only=True, since=since)
        default = self.service.list(future_only=True)
        past_ignored = self.service.list(since=since)

        self.assertEqual(["Missed Tuesday", "Today"], [i["name"] for i in widened])
        self.assertEqual(["Today"], [i["name"] for i in default])
        self.assertEqual(3, len(past_ignored))

    def test_list_preserves_archive_future_and_limit_filters(self):
        self.service.create(self.workout(date="2026-09-19", name="Past"))
        self.id = uuid.UUID("22345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-20", name="Today"))
        self.id = uuid.UUID("32345678-1234-5678-1234-567812345678")
        self.service.create(
            self.workout(date="2026-09-21", name="Archived", archived=True)
        )
        self.id = uuid.UUID("42345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-22", name="Future"))

        visible = self.service.list()
        archived = self.service.list(include_archived=True)
        future = self.service.list(future_only=True)
        bounded = self.service.list(limit=1)
        bounded_with_archived = self.service.list(limit=1, include_archived=True)

        self.assertEqual(
            [item["name"] for item in visible], ["Past", "Today", "Future"]
        )
        self.assertEqual(
            [item["name"] for item in archived],
            ["Past", "Today", "Archived", "Future"],
        )
        self.assertEqual([item["name"] for item in future], ["Today", "Future"])
        self.assertEqual(len(bounded), 1)
        self.assertEqual(len(bounded_with_archived), 2)

    def test_list_between_reads_only_unarchived_units_of_the_day_range(self):
        for index, (day, name, archived) in enumerate(
            (
                ("2026-09-18", "Before", False),
                ("2026-09-19", "Edge start", False),
                ("2026-09-20", "Archived", True),
                ("2026-09-20", "Middle", False),
                ("2026-09-21", "Edge end", False),
                ("2026-09-22", "After", False),
            )
        ):
            self.id = uuid.UUID(f"{index + 1}2345678-1234-5678-1234-567812345678")
            self.service.create(self.workout(date=day, name=name, archived=archived))

        listed = self.service.list_between(date(2026, 9, 19), date(2026, 9, 21))

        self.assertEqual(
            ["Edge start", "Middle", "Edge end"], [item["name"] for item in listed]
        )

    def test_limited_list_is_anchored_on_today_while_future_list_keeps_earliest(self):
        rows = (
            ("2026-09-18", "Past 1"),
            ("2026-09-19", "Past 2"),
            ("2026-09-21", "Future 1"),
            ("2026-09-24", "Future 2"),
            ("2026-09-28", "Future 3"),
            ("2026-10-02", "Future 4"),
        )
        for index, (day, name) in enumerate(rows):
            self.id = uuid.UUID(f"{index + 1}2345678-1234-5678-1234-567812345678")
            self.service.create(self.workout(date=day, name=name))
        self.id = uuid.UUID("72345678-1234-5678-1234-567812345678")
        self.service.create(
            self.workout(date="2026-10-05", name="Archived", archived=True)
        )

        newest = self.service.list(3)
        upcoming = self.service.list(3, future_only=True)

        self.assertEqual(
            [item["name"] for item in newest], ["Past 2", "Future 1", "Future 2"]
        )
        self.assertEqual(
            [item["name"] for item in upcoming], ["Future 1", "Future 2", "Future 3"]
        )

    def _create_days(self, days):
        for index, (day, name) in enumerate(days):
            self.id = uuid.UUID(f"{index + 1:x}2345678-1234-5678-1234-567812345678")
            self.service.create(self.workout(date=day, name=name))

    def test_limited_list_keeps_the_nearest_upcoming_units_when_future_overflows(self):
        self._create_days(
            [("2026-09-20", "Today")]
            + [(f"2026-10-{day:02d}", f"Later {day}") for day in range(1, 8)]
        )

        window = self.service.list(4)

        self.assertEqual(
            [item["name"] for item in window],
            ["Today", "Later 1", "Later 2", "Later 3"],
        )

    def test_limited_list_gives_unused_upcoming_share_to_recent_past(self):
        self._create_days(
            [(f"2026-09-{day:02d}", f"Past {day}") for day in range(10, 16)]
            + [("2026-09-21", "Future 1")]
        )

        window = self.service.list(4)

        self.assertEqual(
            [item["name"] for item in window],
            ["Past 13", "Past 14", "Past 15", "Future 1"],
        )

    def test_list_for_coach_returns_canonical_future_local_units_with_limit(self):
        self.service.create(self.workout(date="2026-09-19", name="Past"))
        self.id = uuid.UUID("22345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-20", name="Today"))
        self.id = uuid.UUID("32345678-1234-5678-1234-567812345678")
        self.service.create(
            self.workout(date="2026-09-21", name="Archived", archived=True)
        )
        self.id = uuid.UUID("42345678-1234-5678-1234-567812345678")
        deleted = self.service.create(self.workout(date="2026-09-22", name="Deleted"))
        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?",
                (deleted["id"],),
            ).fetchone()
            payload = json.loads(row["payload"])
            payload["local_deleted"] = True
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (json.dumps(payload), deleted["id"]),
            )
        self.id = uuid.UUID("52345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-23", name="Future"))

        result = self.service.list_for_coach(limit=2)
        bounded = self.service.list_for_coach(limit=1)

        self.assertEqual(set(result), {"local", "intervals", "canonical", "source"})
        self.assertEqual(result["intervals"], [])
        self.assertEqual(result["source"], "local")
        self.assertEqual(
            [item["name"] for item in result["local"]], ["Today", "Future"]
        )
        self.assertEqual(len(result["canonical"]), 2)
        self.assertEqual(
            [item["name"] for item in result["canonical"]], ["Today", "Future"]
        )
        self.assertEqual(
            [item["date"] for item in result["canonical"]],
            ["2026-09-20", "2026-09-23"],
        )
        self.assertTrue(all(item["is_local"] for item in result["canonical"]))
        self.assertTrue(all(not item["is_remote"] for item in result["canonical"]))
        self.assertTrue(
            all(item["sync_source"] == "local" for item in result["canonical"])
        )
        self.assertEqual([item["name"] for item in bounded["canonical"]], ["Today"])

    def test_update_resets_local_sync_metadata_records_effective_before_and_bumps_revision(
        self,
    ):
        self.service.create(self.workout())
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_error='old error', "
                "sync_conflict='old conflict' WHERE local_id=?",
                (str(self.id),),
            )

        with patch(
            "backend.planning.planned_unit_service.change_history.record_change",
            wraps=change_history.record_change,
        ) as record_change:
            result = self.service.update(str(self.id), {"name": "Neuer Lauf"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result["status"], "local")
        self.assertEqual(payload["name"], "Neuer Lauf")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(history[0]["action"], "create")
        self.assertEqual(history[1]["action"], "update")
        self.assertEqual(revision, 2)
        before = record_change.call_args.args[4]
        after = record_change.call_args.args[5]
        self.assertEqual(before["sync_status"], "synced")
        self.assertEqual(after["sync_status"], "local")
        self.assertEqual(self.events, ["changed"])

    def test_update_rejects_invalid_duration_and_past_date_without_saving(self):
        self.service.create(self.workout())
        before = self.state()
        for values in (
            {"duration_minutes": 0},
            {"duration_minutes": 2000},
            {"duration_minutes": "45.5"},
            {"date": "2026-08-20"},
        ):
            with self.subTest(values=values), self.assertRaises(AppError) as caught:
                self.service.update(str(self.id), values)
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.state(), before)
        self.service.update(str(self.id), {"duration_minutes": "30"})
        payload = json.loads(self.state()[0][0]["payload"])
        self.assertEqual(payload["duration_minutes"], 30)

    def test_unknown_start_stays_unknown_across_date_move_and_undo(self):
        self.service.create(self.workout())
        self.service.update(str(self.id), {"date": "2026-09-23"})
        payload = json.loads(self.state()[0][0]["payload"])
        self.assertIsNone(known_start(payload))

    def test_environment_only_update_is_persisted(self):
        self.service.create(self.workout())

        self.service.update(str(self.id), {"environment": "indoor"})

        planned, _history, _revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(payload["environment"], "indoor")

    def test_focus_update_is_persisted_recorded_and_clearable(self):
        self.service.create(self.workout())

        self.service.update(str(self.id), {"session_focus": "tempo"})
        planned, _history, _revision = self.state()
        self.assertEqual(json.loads(planned[0]["payload"])["session_focus"], "tempo")
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT diff FROM change_history WHERE action='update'"
            ).fetchone()
        diff = json.loads(row["diff"])["fields"]
        self.assertEqual(diff["session_focus"]["after"], "tempo")

        self.service.update(str(self.id), {"session_focus": None})
        planned, _history, _revision = self.state()
        self.assertNotIn("session_focus", json.loads(planned[0]["payload"]))

        with self.assertRaises(AppError):
            self.service.update(str(self.id), {"session_focus": "legs"})

    def test_focus_only_update_keeps_the_sync_state(self):
        self.service.create(self.workout())
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_dirty=0 "
                "WHERE local_id=?",
                (str(self.id),),
            )

        self.service.update(str(self.id), {"session_focus": "easy"})

        planned, _history, _revision = self.state()
        self.assertEqual(
            (planned[0]["sync_state"], planned[0]["sync_dirty"]), ("synced", 0)
        )
        self.assertEqual(json.loads(planned[0]["payload"])["session_focus"], "easy")

        self.service.update(str(self.id), {"name": "Anders"})
        planned, _history, _revision = self.state()
        self.assertEqual(planned[0]["sync_state"], "local")

    def test_undoing_a_focus_edit_keeps_the_sync_state(self):
        self.service.create(self.workout())
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_dirty=0 "
                "WHERE local_id=?",
                (str(self.id),),
            )
        self.service.update(str(self.id), {"session_focus": "easy"})
        with self.manager.reader() as db:
            current = db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (str(self.id),)
            ).fetchone()
        target = {**json.loads(current["payload"])}
        target.pop("session_focus")
        with self.manager.unit_of_work() as db:
            self.service.restore_in_transaction(
                db, str(self.id), dict(current), target, "undo"
            )

        planned, _history, _revision = self.state()
        self.assertEqual(
            (planned[0]["sync_state"], planned[0]["sync_dirty"]), ("synced", 0)
        )
        self.assertNotIn("session_focus", json.loads(planned[0]["payload"]))

    def mark_synced(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_dirty=0 "
                "WHERE local_id=?",
                (str(self.id),),
            )

    def synced_capped_unit(self, focus):
        self.service.create(self.workout())
        self.service.update(
            str(self.id),
            {"session_focus": focus, "hr_cap": hr_cap(HR_CAP_PERCENT["easy"])},
        )
        self.mark_synced()

    def sync_state(self):
        planned, _history, _revision = self.state()
        return planned[0]["sync_state"], planned[0]["sync_dirty"]

    def test_a_focus_edit_that_changes_the_exported_cap_marks_the_unit_pending(self):
        # The stored cap applies only to a capped focus, so the label decides
        # whether the watch gets the bpm range or the zone text.
        self.synced_capped_unit("endurance")
        self.service.update(str(self.id), {"session_focus": "easy"})
        self.assertEqual(self.sync_state(), ("local", 1))

        self.mark_synced()
        self.service.update(str(self.id), {"session_focus": "endurance"})
        self.assertEqual(self.sync_state(), ("local", 1))

    def test_a_focus_edit_that_keeps_the_exported_cap_stays_synced(self):
        self.synced_capped_unit("easy")
        self.service.update(str(self.id), {"session_focus": "long"})
        self.assertEqual(self.sync_state(), ("synced", 0))

    def test_undoing_a_focus_edit_that_changes_the_cap_marks_the_unit_pending(self):
        self.synced_capped_unit("endurance")
        self.service.update(str(self.id), {"session_focus": "easy"})
        self.assertEqual(self.sync_state(), ("local", 1))
        self.mark_synced()
        with self.manager.reader() as db:
            current = db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (str(self.id),)
            ).fetchone()
        target = {**json.loads(current["payload"]), "session_focus": "endurance"}
        with self.manager.unit_of_work() as db:
            self.service.restore_in_transaction(
                db, str(self.id), dict(current), target, "undo"
            )
        self.assertEqual(self.sync_state(), ("local", 1))

    def test_archive_and_restore_are_dirty_local_updates(self):
        self.service.create(self.workout())

        archived = self.service.update(str(self.id), {"action": "archive"})
        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertTrue(archived["library_entry"]["archived"])
        self.assertTrue(payload["archived"])
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(history[-1]["action"], "update")
        self.assertEqual(revision, 2)

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_error='stale', sync_conflict='stale' "
                "WHERE local_id=?",
                (str(self.id),),
            )
        restored = self.service.update(str(self.id), {"action": "restore"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertFalse(restored["library_entry"]["archived"])
        self.assertFalse(payload["archived"])
        self.assertFalse(payload.get("local_deleted", False))
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(
            [row["action"] for row in history], ["create", "update", "update"]
        )
        self.assertEqual(revision, 3)

    def test_delete_keeps_audited_tombstone_and_does_not_physically_delete(self):
        self.service.create(self.workout())

        result = self.service.update(str(self.id), {"action": "delete"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result, {"status": "deleted", "local_id": str(self.id)})
        self.assertTrue(payload["local_deleted"])
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["sync_status"], "local")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertEqual([row["action"] for row in history], ["create", "delete"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, ["changed"])

    def test_missing_corrupt_and_undated_rows_keep_their_error_contracts(self):
        cases = (
            (
                uuid.UUID("52345678-1234-5678-1234-567812345678"),
                None,
                404,
                "Lokale Planung nicht gefunden.",
            ),
            (
                uuid.UUID("62345678-1234-5678-1234-567812345678"),
                "not-json",
                500,
                "Die lokale Planung ist beschädigt.",
            ),
            (
                uuid.UUID("72345678-1234-5678-1234-567812345678"),
                json.dumps({"sport": "Run"}),
                403,
                "Nur lokale geplante Einheiten können bearbeitet werden.",
            ),
        )
        for local_id, payload, status, message in cases:
            with self.subTest(status=status):
                row = (
                    None
                    if payload is None
                    else {
                        "payload": payload,
                        "external_id": None,
                        "sync_state": "local",
                    }
                )
                with self.assertRaises(AppError) as caught:
                    self.service.update(
                        str(local_id), {"name": "Changed"}, db=StaticRowDb(row)
                    )
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.message, message)
                self.assertEqual(self.events, [])

    def test_date_conflict_is_preserved_and_skip_flag_bypasses_conflict_service(self):
        self.service.create(self.workout())
        self.calendar_conflicts.results = [{"kind": "local_library"}]
        with self.assertRaises(AppError) as caught:
            self.service.update(str(self.id), {"date": "2026-09-23"})

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            caught.exception.message,
            "Die lokale Einheit kann wegen einer bestehenden Kalendereinheit nicht verschoben werden.",
        )
        self.assertEqual(len(self.calendar_conflicts.calls), 1)
        self.assertEqual(self.calendar_conflicts.calls[0][0]["date"], "2026-09-23")
        self.assertEqual(self.calendar_conflicts.calls[0][1], {str(self.id)})
        self.assertEqual(len(self.state()[0]), 1)
        self.assertEqual(self.state()[2], 1)
        self.assertEqual(self.events, [])

        self.calendar_conflicts.results = []
        result = self.service.update(
            str(self.id), {"date": "2026-09-23"}, skip_calendar_conflict=True
        )
        self.assertEqual(result["library_entry"]["date"], "2026-09-23")
        self.assertEqual(len(self.calendar_conflicts.calls), 1)
        self.assertEqual(self.state()[2], 2)

    def test_skip_flag_does_not_bypass_calendar_constraints(self):
        self.service.create(self.workout())
        self.calendar_conflicts.constraint_results = [{"constraint": "[NO_INTENSITY]"}]

        with self.assertRaises(AppError) as caught:
            self.service.update(
                str(self.id),
                {"name": "Hard intervals"},
                skip_calendar_conflict=True,
            )

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "plan_date_conflict")
        self.assertEqual(len(self.calendar_conflicts.constraint_calls), 2)

    def test_marker_conflict_on_create_names_the_planned_day_and_marker(self):
        self.calendar_conflicts.constraint_results = [
            {"constraint": "[SHORT_ONLY]", "reason": "short_only", "date": "2026-09-21"}
        ]

        with self.assertRaises(AppError) as caught:
            self.service.create(self.workout())

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "plan_date_conflict")
        self.assertEqual(
            caught.exception.message,
            "Am 21.09.2026 ist „Nur kurze Einheiten“ eingetragen. "
            "Die lokale Einheit verletzt diese Kalenderbeschränkung.",
        )

    def test_marker_conflict_on_update_falls_back_to_constraint_marker(self):
        self.service.create(self.workout())
        self.calendar_conflicts.constraint_results = [{"constraint": "[NO_INTENSITY]"}]

        with self.assertRaises(AppError) as caught:
            self.service.update(str(self.id), {"name": "Hard intervals"})

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "plan_date_conflict")
        self.assertIn(
            "Am 21.09.2026 ist „Keine Intensität“ eingetragen.",
            caught.exception.message,
        )

    def test_external_transaction_owns_commit_revision_and_event_publication(self):
        manager = CountingDatabaseManager(self.manager)
        service = PlannedUnitService(
            manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        service.create(self.workout())
        self.events.clear()

        before = manager.unit_of_work_calls
        with self.manager.unit_of_work() as db:
            service.update(
                str(self.id),
                {"name": "External ohne Revision"},
                bump_planning_revision=False,
                db=db,
            )
            self.assertEqual(manager.unit_of_work_calls, before)
            self.assertEqual(
                db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[
                    "revision"
                ],
                1,
            )
        self.assertEqual(self.events, [])

        with self.manager.unit_of_work() as db:
            service.update(str(self.id), {"name": "External mit Revision"}, db=db)
            self.assertEqual(
                db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[
                    "revision"
                ],
                2,
            )
        self.assertEqual(self.events, [])
        self.assertEqual(
            json.loads(self.state()[0][0]["payload"])["name"], "External mit Revision"
        )

    def test_history_and_revision_failures_roll_back_and_do_not_publish(self):
        self.service.create(self.workout())
        self.events.clear()
        before = self.state()
        with (
            patch(
                "backend.planning.planned_unit_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.update(str(self.id), {"name": "Not committed"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

        with (
            patch.object(
                self.service._planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision unavailable"),
        ):
            self.service.update(str(self.id), {"name": "Also not committed"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

    def test_event_callback_runs_once_after_own_transaction_commits(self):
        self.service.create(self.workout())
        observations = []

        def publish_after_commit():
            with self.manager.reader() as db:
                payload = db.execute(
                    "SELECT payload FROM planned_units WHERE local_id=?",
                    (str(self.id),),
                ).fetchone()["payload"]
            observations.append(json.loads(payload)["name"])

        self.service._publish_change = publish_after_commit
        self.service.update(str(self.id), {"name": "Committed before event"})

        self.assertEqual(observations, ["Committed before event"])

    def test_failed_own_commit_does_not_publish_event(self):
        self.service.create(self.workout())
        self.events.clear()
        service = PlannedUnitService(
            CommitFailingDatabaseManager(self.manager),
            self.service._planning_revision_service,
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        before = self.state()

        with self.assertRaisesRegex(RuntimeError, "commit unavailable"):
            service.update(str(self.id), {"name": "Not committed"})

        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

    def test_restore_existing_in_transaction_restores_visibility_and_local_state(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(
                date="2026-09-23",
                starts_at_local="2026-09-23T07:15:00",
                archived=True,
                local_deleted=True,
            ),
            local_id=entity_id,
            external_id="remote-42",
            sync_status="synced",
        )
        target = {"date": "2026-09-21", "name": "Wiederhergestellt"}
        target_before = dict(target)
        with self.manager.unit_of_work() as db:
            self.service.insert(
                db,
                entry,
                sync_dirty=0,
                sync_state="synced",
            )
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            restored = self.service.restore_in_transaction(
                db, entity_id, current, target, "delete"
            )

        planned, history, revision = self.state()
        stored = json.loads(planned[0]["payload"])
        self.assertEqual(restored, stored)
        self.assertEqual(stored["name"], "Wiederhergestellt")
        self.assertEqual(stored["date"], "2026-09-21")
        self.assertEqual(stored["starts_at_local"], "2026-09-21T07:15:00")
        self.assertFalse(stored["archived"])
        self.assertFalse(stored["local_deleted"])
        self.assertEqual(stored["external_id"], "remote-42")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertEqual(target, target_before)
        self.assertEqual(history, [])
        self.assertEqual(revision, 0)
        self.assertEqual(self.events, [])

    def test_restore_in_transaction_recreates_and_physically_deletes(self):
        entity_id = str(self.id)
        target = self.workout(name="Gelöschte Einheit")
        with self.manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db, entity_id, None, target, "delete"
            )
        self.assertEqual(restored["id"], entity_id)
        self.assertEqual(self.state()[0][0]["sync_state"], "local")

        with self.manager.unit_of_work() as db:
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            deleted = self.service.restore_in_transaction(
                db, entity_id, current, None, "create"
            )
        self.assertIsNone(deleted)
        self.assertEqual(self.state(), ([], [], 0))

    def test_undoing_a_creation_keeps_the_links_of_a_pushed_workout(self):
        entity_id = str(self.service.create(self.workout())["id"])
        repository = RemoteLinkRepository()
        with self.manager.unit_of_work() as db:
            for provider in ("intervals", "garmin"):
                repository.upsert(
                    db,
                    RemoteLink(
                        RemoteEntityKind.PLANNED_UNIT,
                        entity_id,
                        provider,
                        RemoteLinkState.SYNCED,
                        remote_id=f"{provider}-1",
                    ),
                )
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.service,
            None,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            profile_mutation_coordinator=threading.RLock(),
        )
        with self.manager.reader() as db:
            create_id = db.execute(
                "SELECT id FROM change_history WHERE action='create'"
            ).fetchone()["id"]

        result = undo.apply(undo.preview(create_id)["proposal"]["payload"])

        with self.manager.reader() as db:
            kept = [
                link.provider
                for link in repository.list_for_entity(
                    db, RemoteEntityKind.PLANNED_UNIT, entity_id
                )
            ]
            orphans, _count = find_intervals_orphans(db, date(2026, 9, 20))
        # The Intervals.icu event stays reachable as a hidden leftover (#2135):
        # hidden exactly like a deleted unit, and nothing remote happens now.
        self.assertTrue(result["remote_untouched"])
        self.assertEqual(["garmin", "intervals"], sorted(kept))
        self.assertEqual([entity_id], [orphan.local_id for orphan in orphans])
        row = self.state()[0][0]
        hidden = json.loads(row["payload"])
        self.assertEqual(
            (True, True, "local", "local", 1, "intervals-1"),
            (
                hidden["local_deleted"],
                hidden["archived"],
                hidden["sync_status"],
                row["sync_state"],
                row["sync_dirty"],
                hidden["remote_event_id"],
            ),
        )
        # A second undo of the same creation neither revives nor duplicates it.
        with self.assertRaises(AppError) as again:
            undo.preview(create_id)
        self.assertEqual(409, again.exception.status)
        self.assertEqual(1, len(self.state()[0]))

    def test_restore_in_transaction_rejects_conflict_and_corrupt_payload(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(archived=True, local_deleted=True), local_id=entity_id
        )
        with self.manager.unit_of_work() as db:
            self.service.insert(db, entry)
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )

        self.calendar_conflicts.results = [{"id": "occupied"}]
        with self.manager.unit_of_work() as db, self.assertRaises(AppError) as conflict:
            self.service.restore_in_transaction(
                db, entity_id, current, {"archived": False}, "delete"
            )
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(conflict.exception.reason, "plan_date_conflict")

        with self.manager.unit_of_work() as db:
            corrupt = {**current, "payload": "["}
            with self.assertRaises(AppError) as invalid:
                self.service.restore_in_transaction(
                    db, entity_id, corrupt, {"name": "Alt"}, "update"
                )
        self.assertEqual(invalid.exception.status, 409)
        self.assertEqual(
            invalid.exception.message,
            "Die lokale Planung kann nicht wiederhergestellt werden.",
        )

    def test_restore_in_transaction_rolls_back_with_outer_unit_of_work(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(name="Vorher"), local_id=entity_id
        )
        with self.manager.unit_of_work() as db:
            self.service.insert(db, entry)

        with (
            self.assertRaisesRegex(RuntimeError, "abort undo"),
            self.manager.unit_of_work() as db,
        ):
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            self.service.restore_in_transaction(
                db, entity_id, current, {"name": "Nachher"}, "update"
            )
            raise RuntimeError("abort undo")

        stored = json.loads(self.state()[0][0]["payload"])
        self.assertEqual(stored["name"], "Vorher")
        self.assertEqual(self.state()[1:], ([], 0))


class _ExternalCalendarFake:
    def __init__(self):
        self.events = []

    def list_events(self, _limit, training_relevant_only=False):
        return list(self.events)


class PlannedUnitTimeWindowTests(unittest.TestCase):
    """Time-window edits: audit, undo, and same-day collision checks."""

    def setUp(self):
        self.manager = temp_database(self, "time-windows.db", row_factory=row_factory)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.ids = (uuid.UUID(int=number) for number in range(1, 100))
        self.external = _ExternalCalendarFake()
        self.conflicts = CalendarConflictService(self.manager, self.external)
        self.revisions = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.service = PlannedUnitService(
            self.manager,
            self.revisions,
            lambda: NOW,
            lambda: TODAY,
            lambda: next(self.ids),
            lambda value: value,
            self.conflicts,
            lambda: None,
        )

    def unit(self, start, duration=60, **overrides):
        entry = self.service.create(
            {
                "date": "2026-09-21",
                "sport": "Run",
                "name": "Lauf",
                "description": f"- {duration}m 60% locker",
                "duration_minutes": duration,
                "starts_at_local": start,
                **overrides,
            }
        )
        return entry["id"]

    def stored(self, local_id):
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
            ).fetchone()
        return json.loads(row["payload"])

    def history_rows(self):
        with self.manager.reader() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT action, diff FROM change_history ORDER BY created_at"
                ).fetchall()
            ]

    def test_time_only_edit_records_history(self):
        local_id = self.unit("2026-09-21T10:00:00")
        before = len(self.history_rows())

        self.service.update(local_id, {"starts_at_local": "2026-09-21T08:30:00"})

        rows = self.history_rows()[before:]
        self.assertEqual([row["action"] for row in rows], ["update"])
        self.assertEqual(
            list(json.loads(rows[0]["diff"])["fields"]), ["starts_at_local"]
        )

    def test_same_day_start_collision_is_rejected(self):
        self.unit("2026-09-21T08:00:00")
        local_id = self.unit("2026-09-21T10:00:00")

        with self.assertRaises(AppError) as caught:
            self.service.update(local_id, {"starts_at_local": "2026-09-21T08:30:00"})

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            self.stored(local_id)["starts_at_local"], "2026-09-21T10:00:00"
        )

    def test_same_day_duration_collision_is_rejected(self):
        self.unit("2026-09-21T10:00:00")
        local_id = self.unit("2026-09-21T08:00:00", duration=30)

        with self.assertRaises(AppError) as caught:
            self.service.update(local_id, {"duration_minutes": 150})

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.stored(local_id)["duration_minutes"], 30)

    def test_non_overlapping_time_change_is_allowed(self):
        self.unit("2026-09-21T08:00:00")
        local_id = self.unit("2026-09-21T10:00:00")

        self.service.update(local_id, {"starts_at_local": "2026-09-21T09:30:00"})

        self.assertEqual(
            self.stored(local_id)["starts_at_local"], "2026-09-21T09:30:00"
        )

    def test_name_only_edit_is_not_blocked_by_existing_external_overlap(self):
        local_id = self.unit("2026-09-21T10:00:00")
        self.external.events = [
            {
                "id": "race-1",
                "name": "Wettkampf",
                "starts_at_local": "2026-09-21T10:00:00",
                "duration_minutes": 60,
            }
        ]

        self.service.update(local_id, {"name": "Umbenannt"})
        self.assertEqual(self.stored(local_id)["name"], "Umbenannt")

        with self.assertRaises(AppError) as caught:
            self.service.update(local_id, {"starts_at_local": "2026-09-21T10:30:00"})
        self.assertEqual(caught.exception.status, 409)

    def test_name_and_time_edit_undo_restores_exact_timestamp(self):
        local_id = self.unit("2026-09-21T10:00:00")
        self.service.update(
            local_id,
            {"name": "Neu", "starts_at_local": "2026-09-21T08:15:00"},
        )
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.service,
            None,
            self.revisions,
            profile_mutation_coordinator=threading.RLock(),
        )
        preview = undo.preview(self._update_change_id())
        undo.apply(preview["proposal"]["payload"])

        stored = self.stored(local_id)
        self.assertEqual(stored["starts_at_local"], "2026-09-21T10:00:00")
        self.assertEqual(stored["name"], "Lauf")

    def test_time_only_undo_is_rejected_when_the_old_slot_was_taken(self):
        local_id = self.unit("2026-09-21T10:00:00")
        self.service.update(local_id, {"starts_at_local": "2026-09-21T08:00:00"})
        change_id = self._update_change_id()
        self.unit("2026-09-21T10:00:00")
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.service,
            None,
            self.revisions,
            profile_mutation_coordinator=threading.RLock(),
        )

        with self.assertRaises(AppError) as caught:
            preview = undo.preview(change_id)
            undo.apply(preview["proposal"]["payload"])

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            self.stored(local_id)["starts_at_local"], "2026-09-21T08:00:00"
        )

    def _update_change_id(self):
        with self.manager.reader() as db:
            return db.execute(
                "SELECT id FROM change_history WHERE action='update' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()["id"]

    def test_legacy_row_without_start_field_stays_undoable(self):
        local_id = self.unit("2026-09-21T10:00:00")
        self.service.update(local_id, {"name": "Neu"})
        stored = self.stored(local_id)
        legacy_projection = {
            key: value for key, value in stored.items() if key != "starts_at_local"
        }
        legacy_projection = change_history.audit_projection(
            "planned_unit", legacy_projection
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE change_history SET after_hash=? WHERE action='update'",
                (change_history.audit_hash(legacy_projection),),
            )
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.service,
            None,
            self.revisions,
            profile_mutation_coordinator=threading.RLock(),
        )

        preview = undo.preview(self._update_change_id())
        undo.apply(preview["proposal"]["payload"])

        self.assertEqual(self.stored(local_id)["name"], "Lauf")
        self.assertEqual(
            self.stored(local_id)["starts_at_local"], "2026-09-21T10:00:00"
        )

    def test_restore_takes_target_time_component_on_the_restored_date(self):
        local_id = self.unit("2026-09-21T10:00:00")
        with self.manager.unit_of_work() as db:
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (local_id,)
                ).fetchone()
            )
            self.service.restore_in_transaction(
                db,
                local_id,
                current,
                {
                    "date": "2026-09-21",
                    "starts_at_local": "2026-09-21T07:15:00",
                    "name": "Lauf",
                },
                "update",
            )

        self.assertEqual(
            self.stored(local_id)["starts_at_local"], "2026-09-21T07:15:00"
        )

    def _validator(self):
        return StructuredTrainingChangeValidator(
            PlanningStateRepository(), self.conflicts
        )

    def test_structured_batch_time_collision_is_rejected(self):
        self.unit("2026-09-21T08:00:00")
        local_id = self.unit("2026-09-21T10:00:00")

        with (
            self.manager.unit_of_work() as db,
            self.assertRaises(AppError) as caught,
        ):
            self._validator().validate_batch(
                [
                    {
                        "action": "update",
                        "local_id": local_id,
                        "starts_at_local": "2026-09-21T08:30:00",
                    }
                ],
                db,
            )

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "plan_date_conflict")

    def test_structured_batch_allows_non_overlapping_and_name_only_changes(self):
        self.unit("2026-09-21T08:00:00")
        local_id = self.unit("2026-09-21T10:00:00")
        self.external.events = [
            {
                "id": "race-1",
                "name": "Wettkampf",
                "starts_at_local": "2026-09-21T10:00:00",
                "duration_minutes": 60,
            }
        ]

        with self.manager.unit_of_work() as db:
            self._validator().validate_batch(
                [{"action": "update", "local_id": local_id, "name": "Umbenannt"}],
                db,
            )
            self._validator().validate_batch(
                [
                    {
                        "action": "update",
                        "local_id": local_id,
                        "starts_at_local": "2026-09-21T06:30:00",
                    }
                ],
                db,
            )


if __name__ == "__main__":
    unittest.main()
