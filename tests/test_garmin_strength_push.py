"""Strength planned units reach Garmin only through the explicit plan_push job."""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import Mock, patch

from support import temp_database

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.coach.proposal_creation import (
    _approved_garmin_arguments,
    _garmin_approval_details,
)
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.planning import planned_units, session_focus, strength_structure
from backend.planning.garmin_orphans import find_orphans, removal_entries
from backend.planning.push_state import (
    attach_push_state,
    garmin_fingerprint,
    pushable_fingerprint,
)
from backend.providers import garmin_strength_workout as mapping
from backend.sync.executor import GarminJobAdapter
from backend.sync.garmin_strength_push import (
    APP_WORKOUT_CLEANUP_KEY,
    GarminStrengthPushService,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request

U1 = "11111111-1111-4111-8111-111111111111"
U2 = "22222222-2222-4222-8222-222222222222"
U3 = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
TODAY = date(2026, 11, 6)
SQUAT = {"name": "Kniebeuge", "sets": 4, "reps": 5, "kg": 80, "rpe": 8, "rest_s": 180}
PLANK = {"name": "Seitstütz", "sets": 2, "reps": 1}
UNIT = {
    "sport": "WeightTraining",
    "name": "Kraft A",
    "date": "2026-11-09",
    "strength_structure": [SQUAT],
}
needs_catalogue = unittest.skipUnless(
    mapping.catalogue_available(), "garminconnect is not installed"
)


@needs_catalogue
class MappingTests(unittest.TestCase):
    def test_explicit_name_then_exercise_name_then_alias(self) -> None:
        pairs = [
            mapping.resolve_exercise(item)
            for item in (
                {"name": "Kniebeuge", "garmin_exercise": "goblet squat"},
                {"name": "Romanian Deadlift"},
                {"name": "Klimmzüge"},
                {"name": "Copenhagen"},
            )
        ]
        self.assertEqual(
            [
                ("SQUAT", "GOBLET_SQUAT"),
                ("DEADLIFT", "ROMANIAN_DEADLIFT"),
                ("PULL_UP", "PULL_UP"),
                None,
            ],
            [(item.category, item.exercise) if item else None for item in pairs],
        )

    def test_every_alias_names_a_catalogue_exercise(self) -> None:
        for alias, name in mapping._ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIsNotNone(mapping.catalogue_exercise(name))

    def test_no_alias_is_shadowed_by_a_catalogue_name(self) -> None:
        for name, aliases in mapping._ALIAS_GROUPS.items():
            for alias in aliases:
                with self.subTest(alias=alias):
                    found = mapping.resolve_exercise({"name": alias})
                    self.assertEqual(name, found.name if found else None)

    def test_the_athletes_upper_body_exercises_resolve(self) -> None:
        expected = {
            "Hyperextensions": "Hyperextension",
            "Schrägbankdrücken": "Incline Barbell Bench Press",
            "Lat-Pulldown": "Lat Pull-down",
            "Lat Pulldowns": "Lat Pull-down",
            "Face Pulls": "Face Pull",
            "Dips": "Body-weight Dip",
            "Enges Rudern im Sitzen": "V-grip Cable Row",
            "Seitenheben": "Lateral Raise",
            "Bizeps am Seilzug": "Cable Biceps Curl",
        }
        for name, catalogue_name in expected.items():
            with self.subTest(name=name):
                found = mapping.resolve_exercise({"name": name})
                self.assertEqual(catalogue_name, found.name if found else None)

    def test_word_fallback_needs_one_closest_entry(self) -> None:
        found = mapping.resolve_exercise({"name": "Pull Face"})
        self.assertEqual("Face Pull", found.name if found else None)
        # "Press" is part of many entries, none of them closest on its own.
        self.assertIsNone(mapping.resolve_exercise({"name": "Press"}))

    def test_warmup_sets_are_their_own_step_before_the_working_sets(self) -> None:
        document = mapping.strength_workout(
            name="Oberkörper",
            description="",
            exercises=[
                {
                    "name": "Schrägbankdrücken",
                    "sets": 3,
                    "reps": 8,
                    "kg": 40,
                    "rest_s": 90,
                    "warmup": {"sets": 1, "reps": 12, "kg": 20},
                    "note": "nicht bis zum Muskelversagen",
                    "rir": 2,
                },
                {"name": "Dips", "sets": 4, "reps": 10, "kg": 0},
            ],
        )
        warmup, working, dips = document["workoutSegments"][0]["workoutSteps"]
        warmup_step = warmup["workoutSteps"][0]
        self.assertEqual(
            ("warmup", 1, 12.0, 20.0),
            (
                warmup_step["stepType"]["stepTypeKey"],
                warmup["numberOfIterations"],
                warmup_step["endConditionValue"],
                warmup_step["weightValue"],
            ),
        )
        self.assertNotIn("description", warmup_step)
        working_step = working["workoutSteps"][0]
        self.assertEqual(
            ("interval", 3, 40.0, "2 RIR · nicht bis zum Muskelversagen"),
            (
                working_step["stepType"]["stepTypeKey"],
                working["numberOfIterations"],
                working_step["weightValue"],
                working_step["description"],
            ),
        )
        # Bodyweight sends no weight target.
        self.assertNotIn("weightValue", dips["workoutSteps"][0])
        orders = [
            order
            for group in (warmup, working, dips)
            for order in (
                group["stepOrder"],
                *(step["stepOrder"] for step in group["workoutSteps"]),
            )
        ]
        self.assertEqual(list(range(1, 9)), orders)
        self.assertEqual(
            [
                ("warmup", "BENCH_PRESS", "INCLINE_BARBELL_BENCH_PRESS"),
                ("interval", "BENCH_PRESS", "INCLINE_BARBELL_BENCH_PRESS"),
                ("interval", "TRICEPS_EXTENSION", "BODY_WEIGHT_DIP"),
            ],
            mapping.workout_exercise_steps(document),
        )

    def test_weights_are_sent_in_kilograms_not_grams(self) -> None:
        # Garmin Connect showed 40 kg as "40,000 kg" while the value was grams.
        for kg, expected in ((40, 40.0), (12.5, 12.5), (0.5, 0.5)):
            with self.subTest(kg=kg):
                document = mapping.strength_workout(
                    name="Kraft",
                    description="",
                    exercises=[
                        {**SQUAT, "kg": kg, "warmup": {"sets": 1, "reps": 5, "kg": kg}}
                    ],
                )
                warmup, working = document["workoutSegments"][0]["workoutSteps"][:2]
                for group in (warmup, working):
                    step = group["workoutSteps"][0]
                    self.assertEqual(expected, step["weightValue"])
                    self.assertEqual("kilogram", step["weightUnit"]["unitKey"])

    def test_document_has_a_repeat_group_per_exercise(self) -> None:
        document = mapping.strength_workout(
            name="Kraft A", description="Kniebeuge: 4x5", exercises=[SQUAT, PLANK]
        )
        self.assertEqual("strength_training", document["sportType"]["sportTypeKey"])
        squat, plank = document["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(
            ("RepeatGroupDTO", 4, 1),
            (squat["type"], squat["numberOfIterations"], squat["stepOrder"]),
        )
        work, rest = squat["workoutSteps"]
        self.assertEqual(
            {
                "stepOrder": 2,
                "endConditionValue": 5.0,
                "category": "SQUAT",
                "exerciseName": "BARBELL_BACK_SQUAT",
                "weightValue": 80.0,
                "description": "RPE 8",
            },
            {
                key: work[key]
                for key in (
                    "stepOrder",
                    "endConditionValue",
                    "category",
                    "exerciseName",
                    "weightValue",
                    "description",
                )
            },
        )
        self.assertEqual("kilogram", work["weightUnit"]["unitKey"])
        self.assertEqual(
            ("rest", 180.0, 3),
            (
                rest["stepType"]["stepTypeKey"],
                rest["endConditionValue"],
                rest["stepOrder"],
            ),
        )
        # Without rest_s there is no rest step; orders stay unique.
        self.assertEqual(4, plank["stepOrder"])
        self.assertEqual([5], [step["stepOrder"] for step in plank["workoutSteps"]])
        self.assertNotIn("weightValue", plank["workoutSteps"][0])
        self.assertEqual(
            [
                ("interval", "SQUAT", "BARBELL_BACK_SQUAT"),
                ("interval", "PLANK", "SIDE_PLANK"),
            ],
            mapping.workout_exercise_steps(document),
        )

    def test_an_unresolved_exercise_blocks_the_whole_workout(self) -> None:
        with self.assertRaises(mapping.GarminStrengthMappingError) as raised:
            mapping.strength_workout(
                name="X",
                description="",
                exercises=[SQUAT, {"name": "Copenhagen Plank", "sets": 2, "reps": 8}],
            )
        message = str(raised.exception)
        self.assertIn("Copenhagen Plank", message)
        self.assertIn("Vorschläge", message)
        self.assertNotIn("Kniebeuge", message)


@needs_catalogue
class StructureTests(unittest.TestCase):
    def test_explicit_garmin_exercise_is_stored_with_its_pair(self) -> None:
        stored = strength_structure.normalize_structure(
            [{**SQUAT, "garmin_exercise": " barbell  back squat "}]
        )
        assert stored is not None
        self.assertEqual("Barbell Back Squat", stored[0]["garmin_exercise"])
        self.assertEqual(
            {"category": "SQUAT", "exercise": "BARBELL_BACK_SQUAT"},
            stored[0]["garmin_pair"],
        )
        # A stored pair is derived again, never trusted.
        again = strength_structure.normalize_structure(
            [{**stored[0], "garmin_pair": {"category": "X", "exercise": "Y"}}]
        )
        self.assertEqual(stored, again)

    def test_a_request_pair_never_bypasses_the_catalogue(self) -> None:
        for pair in ({"category": "FOO", "exercise": "BAR"}, None):
            with self.subTest(pair=pair), self.assertRaises(AppError):
                strength_structure.normalize_structure(
                    [{**SQUAT, "garmin_exercise": "Frnt Squat", "garmin_pair": pair}]
                )
        # A stored structure keeps its pair after a catalogue rename (#2135).
        renamed = {
            **SQUAT,
            "garmin_exercise": "Retired Squat",
            "garmin_pair": {"category": "SQUAT", "exercise": "RETIRED"},
        }
        self.assertEqual(
            [renamed],
            strength_structure.normalize_structure([renamed], stored=True),
        )
        payload = {"sport": "WeightTraining", "strength_structure": [renamed]}
        self.assertIsNone(pushable_fingerprint(payload, {})[1])

    def test_a_reconcile_keeps_a_structure_with_a_retired_garmin_name(self) -> None:
        stored = {
            **SQUAT,
            "garmin_exercise": "Retired Squat",
            "garmin_pair": {"category": "SQUAT", "exercise": "RETIRED"},
        }
        rendered = strength_structure.render([SQUAT])
        target: dict[str, Any] = {"sport": "WeightTraining", "description": rendered}
        session_focus.carry_focus(target, {"strength_structure": [stored]})
        kept = target["strength_structure"]
        self.assertEqual("Kniebeuge", kept[0]["name"])
        self.assertNotIn("garmin_exercise", kept[0])

    def test_unknown_garmin_exercise_is_rejected_with_suggestions(self) -> None:
        with self.assertRaises(AppError) as raised:
            strength_structure.normalize_structure(
                [{**SQUAT, "garmin_exercise": "Squat of Doom"}]
            )
        self.assertEqual("invalid_strength_structure", raised.exception.reason)
        self.assertIn("Vorschläge", str(raised.exception))

    def test_no_garmin_field_leaves_the_structure_unchanged(self) -> None:
        self.assertEqual(
            [
                {
                    key: SQUAT[key]
                    for key in ("name", "sets", "reps", "kg", "rpe", "rest_s")
                }
            ],
            strength_structure.normalize_structure([SQUAT]),
        )


class JobValidationTests(unittest.TestCase):
    def normalize(self, provider: str, entries: list) -> dict:
        return normalize_sync_job_request(
            provider, "plan_push", {"entries": entries}, all_sync_days=90
        )

    def test_garmin_accepts_hashed_and_remove_entries(self) -> None:
        result = self.normalize(
            "garmin",
            [
                {"library_workout_id": U1, "expected_payload_hash": "a" * 64},
                {"library_workout_id": U2, "remove": True},
            ],
        )
        self.assertEqual(
            [
                {"library_workout_id": U1, "expected_payload_hash": "a" * 64},
                {"library_workout_id": U2, "remove": True},
            ],
            result["payload"]["entries"],
        )

    def test_remove_is_garmin_and_wahoo_only_and_must_be_true(self) -> None:
        self.assertEqual(
            [{"library_workout_id": U1, "remove": True}],
            self.normalize("wahoo", [{"library_workout_id": U1, "remove": True}])[
                "payload"
            ]["entries"],
        )
        for provider, entry in (
            ("wahoo", {"library_workout_id": U1, "remove": False}),
            ("intervals", {"library_workout_id": U1, "remove": True}),
            ("garmin", {"library_workout_id": U1, "remove": False}),
            ("garmin", {"library_workout_id": U1}),
        ):
            with (
                self.subTest(provider=provider, entry=entry),
                self.assertRaises(JobValidationError),
            ):
                self.normalize(provider, [entry])

    def test_the_adapter_routes_only_plan_push_to_the_push_service(self) -> None:
        push, jobs = Mock(), Mock()
        push.sync.return_value = {"ok": True}
        adapter = GarminJobAdapter(jobs=jobs, plan_push=push)
        entries = [{"library_workout_id": U1, "remove": True}]
        adapter.execute({"id": "j"}, {"entries": entries}, "r", job_type="plan_push")
        push.sync.assert_called_once_with({"entries": entries})
        adapter.execute(
            {"id": "j"},
            {"entries": entries, "repair": True},
            "r",
            job_type="plan_push",
        )
        self.assertEqual(
            {"entries": entries, "repair": True}, push.sync.call_args.args[0]
        )
        adapter.execute({"id": "j"}, {}, "r", job_type="refresh")
        jobs.execute.assert_called_once()


class FakeGarmin:
    """In-memory Garmin workouts and schedules; records calls, never the network."""

    def __init__(self) -> None:
        self.workouts: dict[str, dict] = {}
        self.schedules: dict[str, tuple[str, str]] = {}
        self.calls: list[tuple] = []
        self.next_id = 500
        self.blank_names = False
        self.fail: BaseException | None = None

    def _id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def upload_workout(self, document):
        self._check()
        workout_id = self._id()
        self.calls.append(("upload", workout_id))
        stored = json.loads(json.dumps(document))
        if self.blank_names:
            for group in stored["workoutSegments"][0]["workoutSteps"]:
                group["workoutSteps"][0]["exerciseName"] = None
        self.workouts[workout_id] = stored
        return {"workoutId": int(workout_id), "workoutName": document["workoutName"]}

    def update_workout(self, workout_id, document):
        self._check()
        self.calls.append(("update", workout_id))
        if workout_id not in self.workouts:
            raise _not_found()
        self.workouts[workout_id] = json.loads(json.dumps(document))
        return {}

    def get_workout_by_id(self, workout_id):
        self.calls.append(("get", workout_id))
        return self.workouts[workout_id]

    def delete_workout(self, workout_id):
        self.calls.append(("delete", workout_id))
        if self.workouts.pop(workout_id, None) is None:
            raise _not_found()

    def schedule_workout(self, workout_id, day):
        self._check()
        schedule_id = self._id()
        self.calls.append(("schedule", workout_id, day))
        self.schedules[schedule_id] = (workout_id, day)
        return {"workoutScheduleId": int(schedule_id), "calendarDate": day}

    def get_scheduled_workouts_by_period(self, start, end):
        self.calls.append(("period", start))
        return [
            {"workoutScheduleId": int(sid), "workout": {"workoutId": int(wid)}}
            for sid, (wid, day) in self.schedules.items()
            if start <= day <= end
        ]

    def unschedule_workout(self, schedule_id):
        self.calls.append(("unschedule", schedule_id))
        if self.schedules.pop(schedule_id, None) is None:
            raise _not_found()

    def get_workouts(self, start, limit):
        self.calls.append(("list", start))
        rows = [
            {
                "workoutId": int(workout_id),
                "sportType": {
                    "sportTypeKey": workout.get("sport", "strength_training")
                },
            }
            for workout_id, workout in self.workouts.items()
        ]
        return rows[start : start + limit]


class GarminConnectNotFoundError(Exception):
    """Named like the SDK's 404 error, which the service recognizes by name."""


def _not_found() -> Exception:
    return GarminConnectNotFoundError("API Error 404")


def _http_error(status: int) -> Exception:
    error = Exception(f"API Error {status} - SECRET detail")
    error.response = Mock(status_code=status)  # type: ignore[attr-defined]
    return error


@needs_catalogue
class PushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_manager = temp_database(
            self, "push.sqlite", row_factory=row_factory, schema=True
        )
        self.garmin = FakeGarmin()
        self.sessions = 0

        @contextmanager
        def session():
            self.sessions += 1
            yield self.garmin

        self.service = GarminStrengthPushService(
            configured=lambda: True,
            database_manager=lambda: self.database_manager,
            sdk_session=session,
            today=lambda: TODAY,
            now=lambda: NOW,
            redactor=lambda text: text.replace("SECRET", "[redacted]"),
        )

    def insert(self, local_id: str, payload: dict, *, tombstone: int = 0) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, tombstone, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (local_id, local_id, raw, tombstone, "2026-11-01", "2026-11-01"),
            )
        return planned_units.plan_push_payload_hash(raw)

    def update(self, local_id: str, payload: dict) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?", (raw, local_id)
            )
        return planned_units.plan_push_payload_hash(raw)

    def push(self, *entries: tuple[str, str]) -> dict:
        return self.service.sync(
            {
                "entries": [
                    {"library_workout_id": i, "expected_payload_hash": h}
                    for i, h in entries
                ]
            }
        )

    def link(self, local_id: str):
        with self.database_manager.unit_of_work() as db:
            return RemoteLinkRepository().get(
                db, RemoteEntityKind.PLANNED_UNIT, local_id, "garmin"
            )

    def test_push_uploads_verifies_schedules_and_links(self) -> None:
        digest = self.insert(U1, UNIT)

        result = self.push((U1, digest))

        self.assertEqual("ok", result["status"])
        self.assertEqual(
            [("upload", "501"), ("get", "501"), ("schedule", "501", "2026-11-09")],
            self.garmin.calls,
        )
        link = self.link(U1)
        # The link keeps the Garmin fingerprint, not the payload hash, so later
        # Intervals.icu rewrites of the unit do not mark it pending again.
        self.assertEqual(
            ("501", "502", garmin_fingerprint(UNIT)),
            (link.remote_id, link.remote_external_id, link.baseline_hash),
        )
        steps = self.garmin.workouts["501"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(
            "BARBELL_BACK_SQUAT", steps[0]["workoutSteps"][0]["exerciseName"]
        )

    def test_second_push_updates_the_workout_and_moves_its_own_schedule(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        moved = self.update(U1, {**UNIT, "date": "2026-11-10"})
        self.garmin.calls.clear()

        self.push((U1, moved))

        self.assertEqual(
            [
                ("update", "501"),
                ("get", "501"),
                ("unschedule", "502"),
                ("schedule", "501", "2026-11-10"),
            ],
            self.garmin.calls,
        )
        self.assertEqual(["501"], list(self.garmin.workouts))
        self.assertEqual({"503": ("501", "2026-11-10")}, self.garmin.schedules)

    def test_a_resend_replaces_the_workout_sent_with_gram_weights(self) -> None:
        digest = self.insert(U1, UNIT)
        self.push((U1, digest))
        sent = self.garmin.workouts["501"]["workoutSegments"][0]["workoutSteps"]
        sent[0]["workoutSteps"][0]["weightValue"] = 80000.0  # the old, wrong form
        self.garmin.calls.clear()

        result = self.push((U1, digest))

        self.assertEqual("ok", result["status"])
        # The same Garmin workout is updated and rescheduled; nothing is added.
        self.assertEqual(
            [
                ("update", "501"),
                ("get", "501"),
                ("unschedule", "502"),
                ("schedule", "501", "2026-11-09"),
            ],
            self.garmin.calls,
        )
        self.assertEqual(["501"], list(self.garmin.workouts))
        self.assertEqual({"503": ("501", "2026-11-09")}, self.garmin.schedules)
        steps = self.garmin.workouts["501"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(80.0, steps[0]["workoutSteps"][0]["weightValue"])

    def test_a_workout_deleted_at_garmin_is_uploaded_again(self) -> None:
        digest = self.insert(U1, UNIT)
        self.push((U1, digest))
        self.garmin.workouts.clear()
        self.garmin.schedules.clear()

        result = self.push((U1, digest))

        self.assertEqual("ok", result["status"])
        self.assertEqual("503", self.link(U1).remote_id)

    def test_a_failed_schedule_keeps_the_link_so_the_retry_updates(self) -> None:
        digest = self.insert(U1, UNIT)
        original = self.garmin.schedule_workout
        self.garmin.schedule_workout = Mock(side_effect=_http_error(500))  # type: ignore[method-assign]

        self.assertEqual("error", self.push((U1, digest))["status"])
        self.assertEqual(
            ("501", None), (self.link(U1).remote_id, self.link(U1).baseline_hash)
        )

        self.garmin.schedule_workout = original  # type: ignore[method-assign]
        self.assertEqual("ok", self.push((U1, digest))["status"])
        self.assertEqual(["501"], list(self.garmin.workouts))
        self.assertEqual(garmin_fingerprint(UNIT), self.link(U1).baseline_hash)

    def test_a_schedule_without_id_is_looked_up_or_left_incomplete(self) -> None:
        digest = self.insert(U1, UNIT)
        original = self.garmin.schedule_workout

        def no_id(workout_id, day):
            original(workout_id, day)
            return {}

        self.garmin.schedule_workout = no_id  # type: ignore[method-assign]
        self.assertEqual("ok", self.push((U1, digest))["status"])
        self.assertEqual("502", self.link(U1).remote_external_id)

        self.garmin.get_scheduled_workouts_by_period = lambda start, end: []  # type: ignore[method-assign]
        result = self.push((U1, digest))
        self.assertEqual("error", result["status"])
        self.assertIn("Termin-ID", result["results"][0]["error"])
        self.assertIsNone(self.link(U1).baseline_hash)

    def test_blanked_exercise_names_are_deleted_and_never_scheduled(self) -> None:
        self.garmin.blank_names = True

        result = self.push((U1, self.insert(U1, UNIT)))

        self.assertEqual("error", result["status"])
        self.assertIn("nicht alle Übungen", result["results"][0]["error"])
        self.assertEqual({}, self.garmin.workouts)
        self.assertNotIn("schedule", [call[0] for call in self.garmin.calls])
        self.assertIsNone(self.link(U1))

    def test_a_failed_read_back_keeps_the_new_workout_linked(self) -> None:
        digest = self.insert(U1, UNIT)
        original = self.garmin.get_workout_by_id
        self.garmin.get_workout_by_id = Mock(side_effect=_http_error(503))  # type: ignore[method-assign]

        self.assertEqual("error", self.push((U1, digest))["status"])
        self.assertEqual("501", self.link(U1).remote_id)

        self.garmin.get_workout_by_id = original  # type: ignore[method-assign]
        self.push((U1, digest))
        self.assertEqual(["501"], list(self.garmin.workouts))

    def test_a_blanked_update_is_unscheduled_and_kept_linked(self) -> None:
        digest = self.insert(U1, UNIT)
        self.push((U1, digest))
        original = self.garmin.update_workout

        def blanking_update(workout_id, document):
            original(workout_id, document)
            group = self.garmin.workouts[workout_id]["workoutSegments"][0]
            group["workoutSteps"][0]["workoutSteps"][0]["exerciseName"] = None
            return {}

        self.garmin.update_workout = blanking_update  # type: ignore[method-assign]

        result = self.push((U1, digest))

        self.assertEqual("error", result["status"])
        self.assertEqual({}, self.garmin.schedules)
        link = self.link(U1)
        self.assertEqual(
            ("501", None, None),
            (link.remote_id, link.remote_external_id, link.baseline_hash),
        )

    def test_local_problems_write_nothing_and_skip_the_login(self) -> None:
        cases = {
            U1: {
                **UNIT,
                "strength_structure": [{"name": "Copenhagen", "sets": 2, "reps": 8}],
            },
            U2: {**UNIT, "date": "2026-11-05"},
            U3: {**UNIT, "sport": "Ride"},
        }
        entries = [
            (local_id, self.insert(local_id, unit)) for local_id, unit in cases.items()
        ]

        result = self.push(*entries)

        self.assertEqual("error", result["status"])
        self.assertEqual(0, self.sessions)
        errors = [item["error"] for item in result["results"]]
        self.assertIn("Keine Garmin-Übung zugeordnet: Copenhagen", errors[0])
        self.assertIn("Vergangene", errors[1])
        self.assertIn("Nur Krafteinheiten", errors[2])

    def test_stale_hash_and_tombstone_are_conflicts(self) -> None:
        self.insert(U1, UNIT)
        digest = self.insert(U2, UNIT, tombstone=1)

        result = self.push((U1, "b" * 64), (U2, digest))

        self.assertEqual(
            ["conflict", "conflict"], [item["status"] for item in result["results"]]
        )
        self.assertEqual([], self.garmin.calls)

    def test_an_outage_stops_the_remaining_units_without_garmin_text(self) -> None:
        first, second = self.insert(U1, UNIT), self.insert(U2, UNIT)
        self.garmin.fail = _http_error(503)

        result = self.push((U1, first), (U2, second))

        # The first upload failed before any call was recorded; the second never ran.
        self.assertEqual([], self.garmin.calls)
        messages = [item["error"] for item in result["results"]]
        self.assertIn("HTTP 503", messages[0])
        self.assertIn("beendet", messages[1])
        self.assertNotIn("SECRET", " ".join(messages))

    def test_a_client_rejection_fails_only_that_unit(self) -> None:
        first, second = self.insert(U1, UNIT), self.insert(U2, UNIT)
        rejected = _http_error(400)
        original = self.garmin.upload_workout
        calls = {"count": 0}

        def upload(document):
            calls["count"] += 1
            if calls["count"] == 1:
                raise rejected
            return original(document)

        self.garmin.upload_workout = upload  # type: ignore[method-assign]

        result = self.push((U1, first), (U2, second))

        self.assertEqual(
            ["error", "synced"], [item["status"] for item in result["results"]]
        )
        self.assertIn("abgelehnt (HTTP 400)", result["results"][0]["error"])

    def test_remove_deletes_only_the_linked_workout_and_schedule(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.garmin.workouts["999"] = {"workoutName": "Fremd"}
        self.garmin.schedules["998"] = ("999", "2026-11-09")
        self.garmin.calls.clear()

        result = self.service.sync(
            {"entries": [{"library_workout_id": U1, "remove": True}]}
        )

        self.assertEqual(
            ("synced", "removed"),
            (result["results"][0]["status"], result["results"][0]["action"]),
        )
        self.assertEqual([("unschedule", "502"), ("delete", "501")], self.garmin.calls)
        self.assertEqual(["999"], list(self.garmin.workouts))
        self.assertEqual(["998"], list(self.garmin.schedules))
        self.assertIsNone(self.link(U1))

    # --- Orphans: workouts sent for units that no longer exist --------------

    def sync_with_cleanup(self, *entries: tuple[str, str]) -> dict:
        """Run the job the calendar button or the Coach card creates."""
        selected = [
            {"library_workout_id": i, "expected_payload_hash": h} for i, h in entries
        ]
        orphans = find_orphans_listed(self.database_manager)
        return self.service.sync({"entries": [*selected, *removal_entries(orphans)]})

    def orphan_ids(self) -> list[str]:
        return [item.local_id for item in find_orphans_listed(self.database_manager)]

    def retire(self, local_id: str, payload: dict) -> None:
        self.update(local_id, {**payload, "local_deleted": True, "archived": True})

    def test_a_replaced_unit_is_removed_and_its_successor_scheduled(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        replacement = self.insert(U2, {**UNIT, "name": "Kraft B"})
        self.assertEqual([U1], self.orphan_ids())

        result = self.sync_with_cleanup((U2, replacement))

        self.assertEqual("ok", result["status"])
        self.assertEqual(
            ["synced", "synced"], [item["status"] for item in result["results"]]
        )
        self.assertEqual(["503"], list(self.garmin.workouts))
        self.assertEqual({"504": ("503", "2026-11-09")}, self.garmin.schedules)
        self.assertEqual("503", self.link(U2).remote_id)
        self.assertIsNone(self.link(U1))
        self.assertEqual([], self.orphan_ids())

    def test_a_moved_unit_keeps_one_schedule_and_is_no_orphan(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        moved = self.update(U1, {**UNIT, "date": "2026-11-12"})

        self.assertEqual([], self.orphan_ids())
        self.sync_with_cleanup((U1, moved))

        self.assertEqual(
            ["2026-11-12"], [day for _wid, day in self.garmin.schedules.values()]
        )

    def test_deleted_and_vanished_units_are_removed_on_the_next_sync(self) -> None:
        self.push((U1, self.insert(U1, UNIT)), (U2, self.insert(U2, UNIT)))
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE planned_units SET tombstone=1 WHERE local_id=?", (U1,))
            db.execute("DELETE FROM planned_units WHERE local_id=?", (U2,))
        self.assertEqual({U1, U2}, set(self.orphan_ids()))

        result = self.service.sync(
            {"entries": removal_entries(find_orphans_listed(self.database_manager))}
        )

        self.assertEqual("ok", result["status"])
        self.assertEqual({}, self.garmin.workouts)
        self.assertEqual({}, self.garmin.schedules)
        self.assertEqual([], self.orphan_ids())

    def test_a_unit_that_is_no_strength_unit_any_more_is_an_orphan(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.update(U1, {**UNIT, "sport": "Ride"})

        self.assertEqual([U1], self.orphan_ids())

    def test_a_linked_unit_that_became_unpushable_is_an_orphan(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        unmapped = [{"name": "Copenhagen Plank", "sets": 2, "reps": 8}]
        for name, structure in (("empty", []), ("unmapped", unmapped)):
            with self.subTest(structure=name):
                self.update(U1, {**UNIT, "strength_structure": structure})

                self.assertEqual([U1], self.orphan_ids())
                result = self.service.sync(
                    {
                        "entries": removal_entries(
                            find_orphans_listed(self.database_manager)
                        )
                    }
                )

                self.assertEqual("ok", result["status"])
                self.assertIsNone(self.link(U1))
                self.assertEqual({}, self.garmin.workouts)
                self.push((U1, self.update(U1, UNIT)))

    def test_a_linked_unit_with_a_mappable_structure_is_no_orphan(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))

        self.assertEqual([], self.orphan_ids())

    def test_a_unit_with_an_unreadable_payload_is_no_orphan(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE planned_units SET payload='[]' WHERE local_id=?", (U1,))

        self.assertEqual([], self.orphan_ids())

    def test_a_listed_leftover_removed_meanwhile_is_not_a_failure(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        stale = removal_entries(find_orphans_listed(self.database_manager))
        self.service.sync({"entries": stale})

        result = self.service.sync({"entries": stale})

        self.assertEqual("ok", result["status"])
        self.assertEqual("already_synced", result["results"][0]["status"])

    def test_the_card_shows_a_selected_archived_unit_as_a_push(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)

        arguments = _approved_garmin_arguments(
            {"entries": [{"local_id": U1, "remove": False}]},
            self.database_manager,
            TODAY,
        )
        details = _garmin_approval_details(arguments, self.database_manager, TODAY)

        self.assertEqual(
            [("Kraft A", "Kraft an Garmin")],
            [(item["name"], item["sport"]) for item in details],
        )

    def test_a_foreign_garmin_workout_is_never_touched(self) -> None:
        self.garmin.workouts["999"] = {"workoutName": "Mein eigenes"}
        self.garmin.schedules["998"] = ("999", "2026-11-09")
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        self.garmin.calls.clear()

        result = self.sync_with_cleanup()

        self.assertEqual("ok", result["status"])
        self.assertEqual({"999": {"workoutName": "Mein eigenes"}}, self.garmin.workouts)
        self.assertEqual({"998": ("999", "2026-11-09")}, self.garmin.schedules)
        touched = {call[1] for call in self.garmin.calls}
        self.assertTrue({"999", "998"}.isdisjoint(touched))

    def test_a_failed_orphan_removal_keeps_its_link_for_the_next_sync(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        original = self.garmin.delete_workout
        self.garmin.delete_workout = Mock(side_effect=_http_error(500))  # type: ignore[method-assign]

        failed = self.sync_with_cleanup()
        self.assertEqual("error", failed["status"])
        self.assertIn(
            "Altes Garmin-Workout nicht entfernt", failed["results"][0]["error"]
        )
        self.assertEqual([U1], self.orphan_ids())

        self.garmin.delete_workout = original  # type: ignore[method-assign]
        self.assertEqual("ok", self.sync_with_cleanup()["status"])
        self.assertEqual([], self.orphan_ids())

    def test_the_fallback_upload_removes_what_it_replaces(self) -> None:
        digest = self.insert(U1, UNIT)
        self.push((U1, digest))
        # Garmin lost the workout but kept its schedule entry.
        del self.garmin.workouts["501"]
        self.garmin.calls.clear()

        result = self.push((U1, digest))

        self.assertEqual("ok", result["status"])
        self.assertEqual(
            [
                ("update", "501"),
                ("unschedule", "502"),
                ("delete", "501"),
                ("upload", "503"),
                ("get", "503"),
                ("schedule", "503", "2026-11-09"),
            ],
            self.garmin.calls,
        )
        self.assertEqual({"504": ("503", "2026-11-09")}, self.garmin.schedules)
        self.assertEqual(["503"], list(self.garmin.workouts))

    def test_every_sent_workout_carries_the_marker(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))

        description = self.garmin.workouts["501"]["description"]
        self.assertTrue(description.startswith("Pacecraft\n"))
        self.assertIn("Kniebeuge", description)

    def test_the_card_lists_the_removals_it_adds(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        digest = self.insert(U2, {**UNIT, "name": "Kraft B"})

        arguments = _approved_garmin_arguments(
            {"entries": [{"local_id": U2, "remove": False}]},
            self.database_manager,
            TODAY,
        )
        details = _garmin_approval_details(arguments, self.database_manager, TODAY)

        self.assertEqual(
            [
                {"library_workout_id": U2, "expected_payload_hash": digest},
                {"library_workout_id": U1, "remove": True},
            ],
            arguments["entries"],
        )
        self.assertEqual(
            [("Kraft B", "Kraft an Garmin"), ("Kraft A", "Wird bei Garmin entfernt")],
            [(item["name"], item["sport"]) for item in details],
        )

    def test_the_calendar_lists_the_removals_on_a_unit_garmin_waits_for(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        self.retire(U1, UNIT)
        self.insert(U2, {**UNIT, "name": "Kraft B"})
        with self.database_manager.reader() as db:
            rows = db.execute(
                "SELECT local_id, payload, sync_state FROM planned_units "
                "WHERE local_id=?",
                (U2,),
            ).fetchall()
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(
            pairs,
            {},
            orphans=find_orphans_listed(self.database_manager),
            today=TODAY,
        )

        self.assertEqual(
            {"garmin": [{"id": U1, "name": "Kraft A", "date": "2026-11-09"}]},
            pairs[0][1]["push_cleanup"],
        )

    def test_undoing_a_created_unit_keeps_its_garmin_link(self) -> None:
        self.push((U1, self.insert(U1, UNIT)))
        with self.database_manager.unit_of_work() as db:
            db.execute("DELETE FROM planned_units WHERE local_id=?", (U1,))
            RemoteLinkRepository().delete_for_entity(
                db, RemoteEntityKind.PLANNED_UNIT, U1, keep=("garmin",)
            )

        self.assertEqual([U1], self.orphan_ids())
        self.assertEqual(
            "Gelöschte Einheit", find_orphans_listed(self.database_manager)[0].name
        )

    def test_remove_without_a_link_has_nothing_left_to_do(self) -> None:
        # e.g. a listed leftover another sync removed first
        result = self.service.sync(
            {"entries": [{"library_workout_id": U1, "remove": True}]}
        )

        self.assertEqual("ok", result["status"])
        self.assertEqual("already_synced", result["results"][0]["status"])
        self.assertEqual(0, self.sessions)


def find_orphans_listed(database_manager: DatabaseManager) -> list:
    with database_manager.reader() as db:
        return find_orphans(db, TODAY, limit=None)[0]


def past_removal_service(database_manager, garmin) -> GarminStrengthPushService:
    """A push service over ``database_manager`` that writes to the in-memory Garmin."""

    @contextmanager
    def session():
        yield garmin

    return GarminStrengthPushService(
        configured=lambda: True,
        database_manager=lambda: database_manager,
        sdk_session=session,
        today=lambda: TODAY,
        now=lambda: NOW,
        redactor=lambda text: text,
    )


def garmin_link(database_manager, local_id: str):
    with database_manager.unit_of_work() as db:
        return RemoteLinkRepository().get(
            db, RemoteEntityKind.PLANNED_UNIT, local_id, "garmin"
        )


class PastWorkoutRemovalTests(unittest.TestCase):
    """A refresh removes the app's own Garmin workouts of past days (#2185)."""

    def setUp(self) -> None:
        self.database_manager = temp_database(
            self, "past.sqlite", row_factory=row_factory, schema=True
        )
        self.garmin = FakeGarmin()
        self.service = past_removal_service(self.database_manager, self.garmin)
        # The one-time removal of unlinked workouts has its own tests below.
        self.cleanup({"done": True})

    def cleanup(self, state: dict | None = None) -> dict:
        """Set, or read, the one-time removal's stored progress (#2373)."""
        values = KeyValueRepository(str)
        with self.database_manager.unit_of_work() as db:
            if state is not None:
                values.set(db, APP_WORKOUT_CLEANUP_KEY, json.dumps(state))
            return json.loads(values.get(db, APP_WORKOUT_CLEANUP_KEY) or "{}")

    def link(self, local_id: str):
        return garmin_link(self.database_manager, local_id)

    def linked(self, local_id: str, day: str, *, tombstone: int = 0) -> str:
        payload = json.dumps({**UNIT, "date": day})
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, tombstone, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (local_id, local_id, payload, tombstone, "2026-11-01", "2026-11-01"),
            )
        workout_id = self.garmin._id()
        schedule_id = self.garmin._id()
        self.garmin.workouts[workout_id] = {"workoutName": "Kraft A"}
        self.garmin.schedules[schedule_id] = (workout_id, day)
        with self.database_manager.unit_of_work() as db:
            RemoteLinkRepository().upsert(
                db,
                RemoteLink(
                    entity_kind=RemoteEntityKind.PLANNED_UNIT,
                    local_id=local_id,
                    provider="garmin",
                    sync_state=RemoteLinkState.SYNCED,
                    remote_id=workout_id,
                    remote_external_id=schedule_id,
                ),
            )
        return workout_id

    def test_refresh_deletes_linked_workouts_of_past_days_only(self) -> None:
        self.linked(U1, "2026-11-05")
        today = self.linked(U2, "2026-11-06")
        self.linked(U3, "2026-11-04", tombstone=1)
        self.garmin.workouts["999"] = {"workoutName": "eigenes Workout"}
        adapter = GarminJobAdapter(jobs=Mock(), plan_push=self.service)

        adapter.execute({"id": "j"}, {}, "r", job_type="refresh")

        # The past ones are unscheduled and deleted, oldest day first; today's
        # workout and a workout the app never linked stay.
        self.assertEqual(
            [
                ("unschedule", "506"),
                ("delete", "505"),
                ("unschedule", "502"),
                ("delete", "501"),
            ],
            self.garmin.calls,
        )
        self.assertEqual({today, "999"}, set(self.garmin.workouts))
        self.assertEqual(
            [None, today, None],
            [getattr(self.link(u), "remote_id", None) for u in (U1, U2, U3)],
        )

    def test_a_refused_workout_keeps_its_link_and_the_others_still_go(self) -> None:
        refused = self.linked(U3, "2026-11-04")
        self.linked(U1, "2026-11-05")
        delete = self.garmin.delete_workout

        def refuse(workout_id):
            if workout_id == refused:
                raise _http_error(403)
            return delete(workout_id)

        with patch.object(self.garmin, "delete_workout", side_effect=refuse):
            self.assertEqual(1, self.service.remove_past())

        self.assertIsNone(self.link(U1))
        self.assertEqual(refused, self.link(U3).remote_id)

    def test_refusals_bound_the_attempts_of_one_refresh(self) -> None:
        units = [f"{index:08d}-1111-4111-8111-111111111111" for index in range(41)]
        for index, local_id in enumerate(units):
            self.linked(local_id, f"2026-10-{index % 28 + 1:02d}")

        with patch.object(
            self.garmin, "delete_workout", side_effect=_http_error(403)
        ) as delete:
            self.assertEqual(0, self.service.remove_past())

        # Every workout is refused: 40 attempts, then the next refresh goes on.
        self.assertEqual(40, delete.call_count)

    def test_a_workout_already_gone_still_drops_its_link(self) -> None:
        workout_id = self.linked(U1, "2026-11-05")
        del self.garmin.workouts[workout_id]
        self.garmin.schedules.clear()

        self.assertEqual(1, self.service.remove_past())

        self.assertIsNone(self.link(U1))

    def test_a_garmin_failure_keeps_the_links_and_never_raises(self) -> None:
        self.linked(U1, "2026-11-05")
        self.linked(U2, "2026-11-04")
        with patch.object(
            self.garmin, "unschedule_workout", side_effect=_http_error(500)
        ) as unschedule:
            self.assertEqual(0, self.service.remove_past())

        # One remote failure stops the run; both links stay for the next refresh.
        self.assertEqual(1, unschedule.call_count)
        self.assertIsNotNone(self.link(U1))
        self.assertIsNotNone(self.link(U2))

    def test_once_only_the_apps_workouts_without_an_upcoming_day_go(self) -> None:
        # Athlete decision 2026-11-12 (#2373): old app workouts that lost their
        # unit go once; the athlete's own, Intervals.icu copies, upcoming and
        # scheduled ones stay.
        self.cleanup({})
        app = {"description": "Pacecraft\nKniebeuge 4x5"}
        self.garmin.workouts.update(
            {
                "701": dict(app),
                "702": dict(app),
                "703": {"description": "Eigenes Workout\nPacecraft"},
                "704": {"description": ""},
                "705": {**app, "sport": "running"},
            }
        )
        self.garmin.schedules["801"] = ("702", "2026-11-07")
        upcoming = self.linked(U1, "2026-11-08")
        self.garmin.workouts[upcoming] = dict(app)
        # A unit deleted for good keeps its link; its old workout goes too.
        gone = self.linked(U2, "2026-11-02")
        with self.database_manager.unit_of_work() as db:
            db.execute("DELETE FROM planned_units WHERE local_id=?", (U2,))
        self.garmin.workouts[gone] = dict(app)

        self.assertEqual(2, self.service.remove_past())

        self.assertEqual(
            {"702", "703", "704", "705", upcoming}, set(self.garmin.workouts)
        )
        self.assertIsNone(self.link(U2))
        self.assertEqual(upcoming, self.link(U1).remote_id)
        self.assertEqual({"done": True, "checked": ["703", "704"]}, self.cleanup())
        self.garmin.calls.clear()
        self.garmin.workouts["706"] = dict(app)
        self.assertEqual(0, self.service.remove_past())
        self.assertEqual([], self.garmin.calls)

    def test_the_one_time_removal_reads_a_bounded_number_per_refresh(self) -> None:
        self.cleanup({})
        for index in range(45):
            self.garmin.workouts[str(600 + index)] = {"description": "Eigenes"}
        self.garmin.workouts["700"] = {"description": "Pacecraft"}

        self.assertEqual(0, self.service.remove_past())
        self.assertEqual(40, len(self.cleanup()["checked"]))
        self.assertFalse(self.cleanup()["done"])
        self.assertEqual(1, self.service.remove_past())

        self.assertNotIn("700", self.garmin.workouts)
        self.assertEqual(45, len(self.garmin.workouts))
        self.assertTrue(self.cleanup()["done"])

    def test_a_busy_or_unconfigured_garmin_removes_nothing(self) -> None:
        self.linked(U1, "2026-11-05")

        @contextmanager
        def busy():
            raise AppError(409, "busy", reason="garmin_busy")
            yield  # pragma: no cover

        self.service._sdk_session = busy
        self.assertEqual(0, self.service.remove_past())
        self.service._configured = lambda: False
        self.assertEqual(0, self.service.remove_past())
        # A refresh that could not log the SDK in (login or MFA) tries no login.
        self.service._configured = lambda: True
        self.service._sdk_session = Mock(side_effect=AssertionError("no login"))
        self.service._write_ready = lambda: False
        self.assertEqual(0, self.service.remove_past())
        self.assertIsNotNone(self.link(U1))
        self.assertEqual([], self.garmin.calls)


if __name__ == "__main__":
    unittest.main()
