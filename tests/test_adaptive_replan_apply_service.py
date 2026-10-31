from __future__ import annotations

import ast
import inspect
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanAdjustmentRepository, PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import adaptive
from backend.planning import calendar as planning_calendar
from backend.planning.adaptive import AdaptiveReplanApplyService
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.revision import PlanningRevisionService

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class MarkAppliedFailingRepository(PlanAdjustmentRepository):
    def mark_applied(self, db, adjustment_id, payload, status, applied_at):
        super().mark_applied(db, adjustment_id, payload, status, applied_at)
        raise RuntimeError("mark applied failed")


class AdaptiveReplanApplyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "adaptive-apply.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.repository = PlanAdjustmentRepository()
        self._previews_created = 0
        self.revisions = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.service = self.make_service()

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    def make_service(self, repository=None, calendar_conflict_service=None):
        return AdaptiveReplanApplyService(
            self.manager,
            repository or self.repository,
            self.revisions,
            lambda: TODAY,
            lambda: NOW,
            calendar_conflict_service,
        )

    @staticmethod
    def workout(workout_id, day, **overrides):
        return {
            "id": workout_id,
            "date": day,
            "type": "Ride",
            "name": "Easy ride",
            "duration_minutes": 30,
            "description": "- 30m 60% Easy",
            "target": "AUTO",
            **overrides,
        }

    def add_workout(self, workout_id, workout, *, sync_state="local"):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, sync_dirty, sync_state, "
                "sync_conflict, created_at, updated_at) VALUES (?, ?, ?, 0, ?, '', ?, ?)",
                (
                    workout_id,
                    workout_id,
                    json.dumps(workout, ensure_ascii=False),
                    sync_state,
                    NOW,
                    NOW,
                ),
            )

    def add_preview(self, payload, adjustment_id=None, created_at=None):
        adjustment_id = adjustment_id or str(uuid.uuid4())
        self._previews_created += 1
        # Distinct, increasing creation times keep "latest preview" unambiguous.
        created_at = (
            created_at or f"2026-09-20T08:00:{self._previews_created:02d}+00:00"
        )
        with self.manager.unit_of_work() as db:
            self.repository.create_preview(
                db, adjustment_id, json.dumps(payload, ensure_ascii=False), created_at
            )
        return adjustment_id

    def row(self, query, params=()):
        with self.manager.reader() as db:
            return db.execute(query, params).fetchone()

    def test_applies_replacement_audit_revision_and_illness_checkins_atomically(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(
            workout_id,
            "2026-09-21",
            name="Tempo ride",
            description="- 30m 80%",
            workout_doc={"old": True},
            icu_training_load=88,
            icu_intensity=7,
        )
        self.add_workout(workout_id, original, sync_state="synced")
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO athlete_checkins(checkin_date, illness, notes, created_at, updated_at) "
                "VALUES (?, 'allergy', 'preexisting', ?, ?)",
                ("2026-09-20", NOW, NOW),
            )
        replacement = self.workout(
            workout_id,
            "2026-09-21",
            name="Tempo ride",
            duration_minutes=25,
            description="- 25m 50% Easy",
            workout_doc={"new": True},
            icu_training_load=20,
            icu_intensity=2,
        )
        archived_id = str(uuid.uuid4())
        archived = self.workout(archived_id, "2026-09-22")
        self.add_workout(archived_id, archived)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": replacement,
                    },
                    {
                        "library_workout_id": archived_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            archived
                        ),
                        "payload": {
                            **archived,
                            "archived": True,
                            "description": "not valid for workout validation",
                        },
                    },
                ],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            }
        )

        result = self.service.apply(preview_id.upper())

        self.assertEqual(
            result,
            {
                "status": "applied",
                "id": preview_id,
                "updated": 2,
                "updated_checkins": 2,
                "stale": [],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            },
        )
        planned = self.row(
            "SELECT payload, sync_dirty, sync_state FROM planned_units WHERE local_id=?",
            (workout_id,),
        )
        saved = json.loads(planned["payload"])
        self.assertEqual((planned["sync_dirty"], planned["sync_state"]), (1, "local"))
        self.assertEqual(saved["description"], "- 25m 50% Easy")
        self.assertEqual(saved["duration_minutes"], 25)
        self.assertEqual(saved["planned_duration_s"], 1500)
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            self.assertNotIn(key, saved)
        archived_saved = json.loads(
            self.row(
                "SELECT payload FROM planned_units WHERE local_id=?", (archived_id,)
            )["payload"]
        )
        self.assertTrue(archived_saved["archived"])
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        checkins = self.row(
            "SELECT illness, notes FROM athlete_checkins WHERE checkin_date='2026-09-20'"
        )
        self.assertEqual(checkins["illness"], "allergy; cold")
        self.assertEqual(
            checkins["notes"],
            "preexisting · Krankheitspause prognostiziert ab 2026-09-20",
        )
        self.assertIsNotNone(
            self.row("SELECT 1 FROM athlete_checkins WHERE checkin_date='2026-09-21'")
        )
        audit = self.row(
            "SELECT source, before_hash, after_hash, diff FROM change_history "
            "WHERE entity_id=?",
            (workout_id,),
        )
        self.assertEqual(audit["source"], "adaptive_replan")
        self.assertNotEqual(audit["before_hash"], audit["after_hash"])
        self.assertIn("- 30m 80%", audit["diff"])
        applied = json.loads(
            self.row("SELECT payload FROM plan_adjustments WHERE id=?", (preview_id,))[
                "payload"
            ]
        )
        self.assertTrue(applied["illness_pause"]["approved"])
        self.assertEqual(
            self.service.apply(preview_id),
            {"status": "already_applied", "id": preview_id},
        )

    def test_stale_partial_and_past_reasons_are_idempotent(self):
        good_id, changed_id, past_id = (str(uuid.uuid4()) for _ in range(3))
        good = self.workout(good_id, "2026-09-22")
        changed = self.workout(changed_id, "2026-09-22", name="Changed after preview")
        past = self.workout(past_id, "2026-09-19")
        for workout_id, payload in (
            (good_id, good),
            (changed_id, changed),
            (past_id, past),
        ):
            self.add_workout(workout_id, payload)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": good_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            good
                        ),
                        "payload": {**good, "name": "Updated"},
                    },
                    {
                        "library_workout_id": changed_id,
                        "source_fingerprint": "wrong-fingerprint",
                        "payload": {**changed, "name": "Must not overwrite"},
                    },
                    {
                        "library_workout_id": past_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            past
                        ),
                        "payload": {**past, "name": "Must not update past"},
                    },
                    {
                        "library_workout_id": str(uuid.uuid4()),
                        "source_fingerprint": "absent",
                        "payload": good,
                    },
                ]
            }
        )

        result = self.service.apply(preview_id)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(
            [
                (item["library_workout_id"], item["reason"])
                for item in result["stale"][:2]
            ],
            [(changed_id, "changed"), (past_id, "past")],
        )
        self.assertEqual(len(result["stale"]), 3)
        self.assertEqual(result["stale"][2]["reason"], "missing")
        self.assertIsInstance(result["stale"][2]["library_workout_id"], str)
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        self.assertEqual(
            self.service.apply(preview_id),
            {"status": "already_partial", "id": preview_id},
        )

        stale_id = str(uuid.uuid4())
        self.add_workout(stale_id, self.workout(stale_id, "2026-09-22"))
        stale_preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": stale_id,
                        "source_fingerprint": "old",
                        "payload": self.workout(stale_id, "2026-09-22", name="no"),
                    }
                ]
            }
        )
        stale_result = self.service.apply(stale_preview_id)
        self.assertEqual(stale_result["status"], "stale")
        self.assertEqual(stale_result["updated"], 0)
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        self.assertEqual(
            self.service.apply(stale_preview_id),
            {"status": "already_stale", "id": stale_preview_id},
        )

    def test_apply_rechecks_current_calendar_constraints_and_keeps_evidence(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(workout_id, "2026-09-22", name="Tempo ride")
        self.add_workout(workout_id, original)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": {
                            **original,
                            "name": "Easy recovery",
                            "description": "- 20m Z1",
                        },
                    }
                ]
            }
        )

        class Constraints:
            def constraints(self, _workout):
                return [
                    {
                        "id": "event-1",
                        "source": "external_calendar",
                        "constraint": "[NO_TRAINING]",
                        "updated_at": "fresh-sync",
                    }
                ]

        service = self.make_service(calendar_conflict_service=Constraints())
        result = service.apply(preview_id)

        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["stale"][0]["reason"], "calendar_constraint_changed")
        self.assertEqual(result["stale"][0]["events"][0]["updated_at"], "fresh-sync")
        saved = json.loads(
            self.row(
                "SELECT payload FROM planned_units WHERE local_id=?", (workout_id,)
            )["payload"]
        )
        self.assertEqual(saved["name"], "Tempo ride")

    def test_calendar_archive_requires_original_blocker_at_original_date(self):
        for blocker_id in (None, "replacement-event", "original-event"):
            with self.subTest(blocker_id=blocker_id):
                workout_id = str(uuid.uuid4())
                original = self.workout(workout_id, "2026-09-22")
                self.add_workout(workout_id, original)
                preview_id = self.add_preview(
                    {
                        "changes": [
                            {
                                "library_workout_id": workout_id,
                                "date": original["date"],
                                "before": original,
                                "blocking_triggers": ["calendar"],
                                "external_events": [
                                    {"id": "original-event", "no_training": True}
                                ],
                                "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                                    original
                                ),
                                "payload": {
                                    **original,
                                    "archived": True,
                                    "duration_minutes": 0,
                                },
                            }
                        ]
                    }
                )
                checked = []

                class Constraints:
                    def constraints(
                        self, candidate, blocker_id=blocker_id, checked=checked
                    ):
                        checked.append(candidate)
                        if blocker_id is None:
                            return []
                        return [{"id": blocker_id, "reason": "no_training"}]

                result = self.make_service(
                    calendar_conflict_service=Constraints()
                ).apply(preview_id)
                expected = blocker_id == "original-event"
                self.assertEqual(result["updated"], int(expected))
                self.assertEqual(checked[0]["date"], original["date"])
                self.assertEqual(checked[0]["duration_minutes"], 30)
                saved = json.loads(
                    self.row(
                        "SELECT payload FROM planned_units WHERE local_id=?",
                        (workout_id,),
                    )["payload"]
                )
                self.assertEqual(bool(saved.get("archived")), expected)
                if not expected:
                    self.assertEqual(
                        result["stale"][0]["reason"], "calendar_constraint_changed"
                    )

    @staticmethod
    def calendar_event(**marker):
        return {
            "id": "family-1",
            "name": "Family",
            "event_date": "2026-09-22",
            "start_local": "2026-09-22T10:00:00",
            "end_local": "2026-09-22T11:00:00",
            "duration_minutes": 60,
            "training_relevant": True,
            **marker,
        }

    def preview_and_apply(self, drafts, events, feedback=None):
        for draft in drafts:
            self.add_workout(draft["id"], draft)

        class Checkins:
            def context(self):
                return {"today": feedback or {}}

        class PlannedUnits:
            def list(self, _limit, *, future_only=False):
                return drafts

        class Calendar:
            def list_events(self, _limit, training_relevant_only=False):
                return events

        class Weather:
            def state(self, **_kwargs):
                return {"days": []}

        preview = AdaptiveReplanPreviewService(
            self.manager,
            self.repository,
            Checkins(),
            PlannedUnits(),
            Calendar(),
            Weather(),
            lambda: TODAY,
            lambda: NOW,
            lambda: str(uuid.uuid4()),
            56,
            1000,
            3,
            90,
        ).preview()
        service = self.make_service(
            calendar_conflict_service=CalendarConflictService(self.manager, Calendar())
        )
        return preview, service.apply(preview["id"])

    def saved(self, workout_id):
        return json.loads(
            self.row(
                "SELECT payload FROM planned_units WHERE local_id=?", (workout_id,)
            )["payload"]
        )

    def test_short_only_preview_round_trip_applies_within_the_marker_limit(self):
        for minutes in (90, 70):
            with self.subTest(minutes=minutes):
                event = self.calendar_event(short_only=True)
                workout_id = str(uuid.uuid4())
                draft = self.workout(
                    workout_id,
                    "2026-09-22",
                    duration_minutes=minutes,
                    description=f"- {minutes}m 60% Easy",
                )

                preview, result = self.preview_and_apply([draft], [event])

                payload = preview["changes"][0]["payload"]
                self.assertLessEqual(payload["duration_minutes"], 60)
                self.assertIsNone(
                    planning_calendar.calendar_constraint_decision(payload, event)
                )
                self.assertEqual((result["status"], result["updated"]), ("applied", 1))
                self.assertLessEqual(self.saved(workout_id)["duration_minutes"], 60)

    def test_no_intensity_preview_round_trip_applies_easy_replacement(self):
        event = self.calendar_event(no_intensity=True)
        workout_id = str(uuid.uuid4())
        draft = self.workout(
            workout_id,
            "2026-09-22",
            name="Threshold intervals",
            duration_minutes=60,
            description="- 60m 95%",
            target="POWER",
        )

        preview, result = self.preview_and_apply([draft], [event])

        self.assertEqual(
            preview["changes"][0]["payload"]["name"], adaptive.ADAPTIVE_EASY_NAME
        )
        self.assertEqual((result["status"], result["updated"]), ("applied", 1))
        saved = self.saved(workout_id)
        self.assertEqual(saved["name"], adaptive.ADAPTIVE_EASY_NAME)
        self.assertEqual(saved["target"], "AUTO")
        self.assertIsNone(planning_calendar.calendar_constraint_decision(saved, event))

    def test_no_intensity_description_only_hard_keyword_keeps_title_and_applies(self):
        event = self.calendar_event(no_intensity=True)
        workout_id = str(uuid.uuid4())
        draft = self.workout(
            workout_id,
            "2026-09-22",
            name="Morning ride",
            duration_minutes=60,
            description="- 60m threshold",
        )

        preview, result = self.preview_and_apply([draft], [event])

        self.assertEqual(preview["changes"][0]["payload"]["name"], "Morning ride")
        self.assertEqual((result["status"], result["updated"]), ("applied", 1))
        saved = self.saved(workout_id)
        self.assertEqual(saved["name"], "Morning ride")
        self.assertIsNone(planning_calendar.calendar_constraint_decision(saved, event))

    def test_illness_archive_beside_an_ordinary_event_applies(self):
        workout_id = str(uuid.uuid4())
        draft = self.workout(
            workout_id, "2026-09-22", name="Tempo ride", description="- 30m 80%"
        )

        preview, result = self.preview_and_apply(
            [draft],
            [self.calendar_event()],
            {"checkin_date": TODAY.isoformat(), "illness": "Infekt"},
        )

        change = preview["changes"][0]
        self.assertTrue(change["payload"]["archived"])
        self.assertEqual(change["blocking_triggers"], ["illness", "calendar"])
        self.assertEqual((result["status"], result["updated"]), ("applied", 1))
        self.assertTrue(self.saved(workout_id)["archived"])

    def test_apply_keeps_athlete_edits_outside_the_replaced_fields(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(
            workout_id,
            "2026-09-21",
            starts_at_local="2026-09-21T06:30:00",
            plan_id="plan-a",
            plan_name="Plan A",
            external_id="ext-old",
        )
        self.add_workout(workout_id, original)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": {
                            **original,
                            "duration_minutes": 20,
                            "description": "- 20m 50% Easy",
                            "starts_at_local": "2026-09-21T06:30:00",
                        },
                    }
                ]
            }
        )
        edited = {
            **original,
            "starts_at_local": "2026-09-21T18:00:00",
            "plan_id": "plan-b",
            "plan_name": "Plan B",
            "external_id": "ext-new",
        }
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (json.dumps(edited), workout_id),
            )

        result = self.service.apply(preview_id)

        self.assertEqual((result["status"], result["updated"]), ("applied", 1))
        saved = json.loads(
            self.row(
                "SELECT payload FROM planned_units WHERE local_id=?", (workout_id,)
            )["payload"]
        )
        self.assertEqual(saved["description"], "- 20m 50% Easy")
        self.assertEqual(saved["duration_minutes"], 20)
        for key in (
            "starts_at_local",
            "plan_id",
            "plan_name",
            "external_id",
        ):
            self.assertEqual(saved[key], edited[key], key)

    def test_only_the_latest_preview_can_be_applied(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(workout_id, "2026-09-21")
        self.add_workout(workout_id, original)
        change = {
            "library_workout_id": workout_id,
            "source_fingerprint": adaptive.adaptive_workout_fingerprint(original),
            "payload": {**original, "duration_minutes": 20, "description": "- 20m 50%"},
        }
        older_id = self.add_preview({"changes": [change]})
        newer_id = self.add_preview({"changes": [change]})
        before = self._state_snapshot()

        with self.assertRaises(AppError) as superseded:
            self.service.apply(older_id)

        self.assertEqual(superseded.exception.status, 409)
        self.assertEqual(self._state_snapshot(), before)
        self.assertEqual(self.service.apply(newer_id)["status"], "applied")
        self.assertEqual(
            self.service.apply(newer_id),
            {"status": "already_applied", "id": newer_id},
        )
        # A superseded preview that was never applied stays rejected afterwards.
        with self.assertRaises(AppError):
            self.service.apply(older_id)

    def test_previews_with_the_same_timestamp_resolve_to_the_newest(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(workout_id, "2026-09-21")
        self.add_workout(workout_id, original)
        change = {
            "library_workout_id": workout_id,
            "source_fingerprint": adaptive.adaptive_workout_fingerprint(original),
            "payload": {**original, "duration_minutes": 20, "description": "- 20m 50%"},
        }
        older_id = self.add_preview({"changes": [change]}, created_at=NOW)
        newer_id = self.add_preview({"changes": [change]}, created_at=NOW)

        with self.assertRaises(AppError) as superseded:
            self.service.apply(older_id)

        self.assertEqual(superseded.exception.status, 409)
        self.assertEqual(self.service.apply(newer_id)["status"], "applied")

    def test_invalid_uuid_and_missing_preview_raise_app_errors(self):
        with self.assertRaises(AppError) as invalid:
            self.service.apply("not-a-uuid")
        self.assertEqual(
            (invalid.exception.status, invalid.exception.message),
            (400, "Ungültige Plananpassung."),
        )
        with self.assertRaises(AppError) as missing:
            self.service.apply(uuid.uuid4())
        self.assertEqual(
            (missing.exception.status, missing.exception.message),
            (404, "Plananpassung nicht gefunden."),
        )

    def test_non_object_preview_payload_fails_without_writes(self):
        adjustment_id = str(uuid.uuid4())
        with self.manager.unit_of_work() as db:
            self.repository.create_preview(db, adjustment_id, "[]", NOW)
        before = self._state_snapshot()

        with self.assertRaises(AttributeError):
            self.service.apply(adjustment_id)

        self.assertEqual(self._state_snapshot(), before)

    def test_late_mark_applied_failure_rolls_back_all_tables(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(workout_id, "2026-09-21")
        self.add_workout(workout_id, original)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO athlete_checkins(checkin_date, illness, notes, created_at, updated_at) "
                "VALUES ('2026-09-20', 'existing', 'notes', ?, ?)",
                (NOW, NOW),
            )
        adjustment_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": {**original, "name": "Updated"},
                    }
                ],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            }
        )
        before = self._state_snapshot()
        service = self.make_service(MarkAppliedFailingRepository())

        with self.assertRaisesRegex(RuntimeError, "mark applied failed"):
            service.apply(adjustment_id)

        self.assertEqual(self._state_snapshot(), before)

    def _state_snapshot(self):
        with self.manager.reader() as db:
            return {
                table: [
                    dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()
                ]
                for table in (
                    "plan_adjustments",
                    "planned_units",
                    "athlete_checkins",
                    "planning_state",
                    "change_history",
                )
            }

    def test_module_has_no_server_provider_event_imports_or_removed_api(self):
        tree = ast.parse(inspect.getsource(adaptive))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
                modules.extend(alias.name for alias in node.names)
        self.assertTrue(
            all(
                not any(
                    "server" == part.casefold()
                    or "provider" in part.casefold()
                    or "event" in part.casefold()
                    for part in module.split(".")
                )
                for module in modules
            )
        )
        defined_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        self.assertNotIn("AdaptiveDependencies", defined_names)
        self.assertNotIn("apply_adaptive_changes", defined_names)
        self.assertFalse(hasattr(adaptive, "AdaptiveDependencies"))
        self.assertFalse(hasattr(adaptive, "apply_adaptive_changes"))


if __name__ == "__main__":
    unittest.main()
