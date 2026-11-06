"""Strength planned units reach Garmin only through the explicit plan_push job."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

from backend.canonical.vocabulary import RemoteEntityKind
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLinkRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import strength_structure
from backend.providers import garmin_strength_workout as mapping
from backend.sync.executor import GarminJobAdapter
from backend.sync.garmin_strength_push import GarminStrengthPushService
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
                "weightValue": 80000.0,
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
            [("SQUAT", "BARBELL_BACK_SQUAT"), ("PLANK", "SIDE_PLANK")],
            mapping.workout_exercise_pairs(document),
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

    def test_remove_is_garmin_only_and_must_be_true(self) -> None:
        for provider, entry in (
            ("wahoo", {"library_workout_id": U1, "remove": True}),
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
        self.directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.directory.name) / "push.sqlite", sqlite3, row_factory=row_factory
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
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

    def tearDown(self) -> None:
        self.database_manager.close()
        self.directory.cleanup()

    def insert(self, local_id: str, payload: dict, *, tombstone: int = 0) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, tombstone, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (local_id, local_id, raw, tombstone, "2026-11-01", "2026-11-01"),
            )
        return planning_library.library_payload_hash(raw)

    def update(self, local_id: str, payload: dict) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?", (raw, local_id)
            )
        return planning_library.library_payload_hash(raw)

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
        self.assertEqual(
            ("501", "502", digest),
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
        self.assertEqual(digest, self.link(U1).baseline_hash)

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

    def test_remove_without_a_link_is_a_conflict(self) -> None:
        result = self.service.sync(
            {"entries": [{"library_workout_id": U1, "remove": True}]}
        )

        self.assertEqual("conflict", result["results"][0]["status"])
        self.assertEqual(0, self.sessions)


if __name__ == "__main__":
    unittest.main()
