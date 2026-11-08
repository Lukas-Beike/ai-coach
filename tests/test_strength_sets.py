"""Executed strength sets: FIT set messages, Garmin exercise sets and storage.

Synthetic FIT files come from the builder in ``test_fit_file`` and Garmin
payloads are synthetic; no provider data, files or accounts are read.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import UTC, datetime
from typing import Any

from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStrengthSet,
    ActivityStrengthSetSet,
)
from backend.canonical.mapping import IssueReason, MappingIssue
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityDetailOrigin,
    ExerciseCategory,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StrengthSetSource,
    StrengthSetType,
)
from backend.db import row_factory
from backend.db.activity_detail_store import (
    _header,
    detail_sets_for,
    replace_detail_set,
    restamp_detail_set,
    stored_strength_source,
    strength_record_ids,
)
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.providers import fit_activity_detail_mapping as fit_mapper
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from backend.providers.garmin import collect_garmin_activity_detail
from backend.providers.garmin_activity_detail_mapping import map_garmin_activity_detail
from backend.sync.garmin_activity_details import _keeps_corrected_sets
from tests import test_fit_file as fit_builder

ENUM = fit_builder.ENUM
UINT16 = fit_builder.UINT16
UINT32 = fit_builder.UINT32
ID = "987654321"
STAMP = "2026-11-07T08:00:00+00:00"
RETRIEVED = datetime(2026, 11, 7, 7, 30, tzinfo=UTC)
GARMIN_PROVENANCE = Provenance(
    provider=ProviderId.GARMIN,
    source_kind=SourceKind.PROVIDER_REPORTED,
    source_record_id=ID,
    recorded_by=RecordingOrigin.GARMIN,
    retrieved_at=RETRIEVED,
    label=None,
)
RECORD_FIELDS = [(253, UINT32), (3, fit_builder.UINT8)]
# duration, repetitions, weight, set_type, start_time, category, wkt_step_index
SET_FIELDS = [
    (0, UINT32),
    (3, UINT16),
    (4, UINT16),
    (5, fit_builder.UINT8),
    (6, UINT32),
    (7, UINT16),
    (11, UINT16),
]
START = 1_000_000


def _set(**raw: int) -> dict[int, int]:
    names = {
        "duration_ms": 0,
        "reps": 3,
        "weight_16": 4,
        "set_type": 5,
        "start": 6,
        "category": 7,
        "step": 11,
    }
    return {names[name]: value for name, value in raw.items()}


def _fit(sets: list[dict[int, int]], *, records: bool = True) -> bytes:
    builder = fit_builder.FitBuilder()
    if records:
        builder.define(0, 20, RECORD_FIELDS)
        builder.data(0, {253: START, 3: 90})
        builder.data(0, {253: START + 1, 3: 95})
    builder.define(1, 225, SET_FIELDS)
    for row in sets:
        builder.data(1, row)
    return builder.build()


def _strength(result: Any) -> ActivityStrengthSetSet:
    found = [r for r in result.records if isinstance(r, ActivityStrengthSetSet)]
    if len(found) != 1:
        raise AssertionError(f"expected one strength set list, got {len(found)}")
    return found[0]


SQUAT_SETS = [
    _set(
        set_type=1,
        reps=5,
        weight_16=80 * 16,
        duration_ms=30_000,
        start=START + 60,
        category=28,
        step=0x8001,
    ),
    _set(set_type=0, duration_ms=90_000, start=START + 90),
    _set(
        set_type=1,
        reps=5,
        weight_16=82 * 16 + 8,
        duration_ms=31_500,
        start=START + 180,
        category=28,
        step=1,
    ),
    _set(set_type=1, reps=12, weight_16=0, start=START + 300, category=22),
]


class FitStrengthSetMappingTests(unittest.TestCase):
    def map(self, data: bytes) -> Any:
        return map_fit_activity_detail(
            data, provider_activity_id=ID, provenance=GARMIN_PROVENANCE
        )

    def test_set_messages_map_to_one_strength_list_in_canonical_units(self) -> None:
        result = self.map(_fit(SQUAT_SETS))
        strength = _strength(result)
        self.assertEqual(strength.source, StrengthSetSource.FIT_SET_MESSAGES)
        self.assertIs(strength.kind, ActivityDetailKind.STRENGTH_SETS)
        first, rest, second, bodyweight = strength.sets
        self.assertEqual(
            first,
            ActivityStrengthSet(
                index=0,
                set_type=StrengthSetType.ACTIVE,
                exercise_category=ExerciseCategory.SQUAT,
                reps=5,
                weight_kg=80.0,
                duration_s=30.0,
                start_offset_s=60.0,
                workout_step_index=1,
            ),
        )
        self.assertEqual(rest.set_type, StrengthSetType.REST)
        self.assertEqual(
            (rest.duration_s, rest.reps, rest.weight_kg), (90.0, None, None)
        )
        self.assertEqual(second.weight_kg, 82.5)
        # 0 kg is no external load: never stored as a stand-in value.
        self.assertIsNone(bodyweight.weight_kg)
        self.assertEqual(bodyweight.exercise_category, ExerciseCategory.PUSH_UP)
        self.assertIsNone(bodyweight.exercise_name)
        self.assertEqual(result.issues, ())

    def test_without_records_the_first_set_start_is_time_zero(self) -> None:
        strength = _strength(self.map(_fit(SQUAT_SETS, records=False)))
        self.assertEqual(
            [item.start_offset_s for item in strength.sets], [0.0, 30.0, 120.0, 240.0]
        )

    def test_a_set_without_set_type_is_dropped_with_one_issue(self) -> None:
        result = self.map(_fit([_set(reps=5), _set(set_type=1, reps=3), _set(reps=4)]))
        strength = _strength(result)
        self.assertEqual([(i.index, i.reps) for i in strength.sets], [(0, 3)])
        self.assertEqual(
            result.issues, (MappingIssue(ID, "set_type", IssueReason.MISSING),)
        )

    def test_out_of_range_values_become_unknown_with_an_issue(self) -> None:
        result = self.map(_fit([_set(set_type=1, reps=5000, weight_16=60_000)]))
        only = _strength(result).sets[0]
        self.assertEqual((only.reps, only.weight_kg), (None, None))
        self.assertEqual(
            set(result.issues),
            {
                MappingIssue(ID, "reps", IssueReason.OUT_OF_RANGE),
                MappingIssue(ID, "weight_kg", IssueReason.OUT_OF_RANGE),
            },
        )

    def test_categories_follow_the_fit_profile(self) -> None:
        category = fit_mapper._category
        self.assertEqual(category(8), ExerciseCategory.DEADLIFT)
        self.assertEqual(category(17), ExerciseCategory.LUNGE)
        self.assertEqual(category(32), ExerciseCategory.RUN)
        self.assertEqual(category(45), ExerciseCategory.OTHER)
        self.assertIsNone(category(65534))
        self.assertIsNone(category(None))
        self.assertEqual(category([None, 65534, 28, 0]), ExerciseCategory.SQUAT)

    def test_a_file_without_set_messages_yields_no_strength_list(self) -> None:
        builder = fit_builder.FitBuilder()
        builder.define(0, 20, RECORD_FIELDS)
        builder.data(0, {253: START, 3: 90})
        builder.data(0, {253: START + 1, 3: 91})
        result = self.map(builder.build())
        self.assertFalse(
            any(isinstance(r, ActivityStrengthSetSet) for r in result.records)
        )


def _exercise_sets() -> dict[str, Any]:
    return {
        "activityId": int(ID),
        "exerciseSets": [
            {
                "exercises": [
                    {"category": "SQUAT", "name": "GOBLET_SQUAT", "probability": 20.0},
                    {
                        "category": "SQUAT",
                        "name": "BARBELL_BACK_SQUAT",
                        "probability": 79.5,
                    },
                ],
                "duration": 32.4,
                "repetitionCount": 5,
                "weight": 80000.0,
                "setType": "ACTIVE",
                "startTime": "2026-11-06T17:01:00.0",
                "wktStepIndex": 0,
            },
            {"exercises": [], "duration": 90.0, "setType": "REST", "weight": None},
            {
                "exercises": [
                    {"category": "PUSH_UP", "name": None, "probability": 100}
                ],
                "repetitionCount": 15,
                "weight": 0.0,
                "setType": "ACTIVE",
            },
            {
                "exercises": [
                    {"category": "SLED", "name": "Sled push <b>", "probability": 90}
                ],
                "repetitionCount": 1,
                "setType": "ACTIVE",
            },
        ],
    }


class GarminExerciseSetMappingTests(unittest.TestCase):
    def map(self, collected: dict[str, Any]) -> Any:
        return map_garmin_activity_detail(
            {"activity_id": ID, **collected},
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED,
        )

    def test_exercise_sets_map_with_the_most_probable_exercise(self) -> None:
        result = self.map({"exercise_sets": _exercise_sets()})
        strength = _strength(result)
        self.assertEqual(strength.source, StrengthSetSource.GARMIN_EXERCISE_SETS)
        squat, rest, push_up, sled = strength.sets
        self.assertEqual(
            squat,
            ActivityStrengthSet(
                index=0,
                set_type=StrengthSetType.ACTIVE,
                exercise_category=ExerciseCategory.SQUAT,
                exercise_name="BARBELL_BACK_SQUAT",
                reps=5,
                weight_kg=80.0,
                duration_s=32.4,
                workout_step_index=0,
            ),
        )
        self.assertEqual(
            (rest.set_type, rest.duration_s, rest.exercise_category),
            (StrengthSetType.REST, 90.0, None),
        )
        self.assertEqual(
            (push_up.exercise_category, push_up.exercise_name, push_up.weight_kg),
            (ExerciseCategory.PUSH_UP, None, None),
        )
        # An unknown category keeps its code; free text never becomes a name.
        self.assertEqual(
            (sled.exercise_category, sled.exercise_name),
            (ExerciseCategory.OTHER, "SLED"),
        )
        self.assertEqual(result.issues, ())

    def test_exercise_sets_win_over_the_file_and_the_file_is_the_fallback(self) -> None:
        both = _strength(
            self.map({"exercise_sets": _exercise_sets(), "fit": _fit(SQUAT_SETS)})
        )
        self.assertEqual(both.source, StrengthSetSource.GARMIN_EXERCISE_SETS)
        file_only = self.map({"fit": _fit(SQUAT_SETS)})
        self.assertEqual(
            _strength(file_only).source, StrengthSetSource.FIT_SET_MESSAGES
        )
        empty = self.map(
            {"exercise_sets": {"exerciseSets": []}, "fit": _fit(SQUAT_SETS)}
        )
        self.assertEqual(_strength(empty).source, StrengthSetSource.FIT_SET_MESSAGES)

    def test_malformed_parts_give_value_free_issues_and_no_exception(self) -> None:
        cases = (
            (
                {"exerciseSets": "x"},
                MappingIssue(ID, "exercise_sets", IssueReason.INVALID_TYPE),
            ),
            (
                {"exerciseSets": [7]},
                MappingIssue(ID, "exerciseSets", IssueReason.INVALID_TYPE),
            ),
            (
                {"exerciseSets": [{"setType": "WARMUP"}]},
                MappingIssue(ID, "setType", IssueReason.INVALID_TYPE),
            ),
            (
                {"exerciseSets": [{"setType": None}]},
                MappingIssue(ID, "setType", IssueReason.MISSING),
            ),
            (
                {"exerciseSets": [{"setType": "ACTIVE", "weight": -5}]},
                MappingIssue(ID, "weight_kg", IssueReason.OUT_OF_RANGE),
            ),
        )
        for payload, issue in cases:
            with self.subTest(payload=payload):
                result = self.map({"exercise_sets": payload})
                self.assertIn(issue, result.issues)

    def test_no_exercise_sets_part_yields_no_strength_list(self) -> None:
        for collected in (
            {},
            {"exercise_sets": None},
            {"exercise_sets": {"exerciseSets": None}},
        ):
            with self.subTest(collected=collected):
                result = self.map(collected)
                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, ())


class StrengthSetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")
        for activity_id, provider_id, sport in (
            ("act_1", ID, "strength"),
            ("act_2", "222", "ride"),
        ):
            self.db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, started_at, created_at, updated_at) "
                "VALUES (?, 'garmin', ?, ?, ?, ?)",
                (activity_id, provider_id, STAMP, STAMP, STAMP),
            )
            self.db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
                "state, mapper_version, source_kind, recorded_by, sport, environment, "
                "started_at, load_model, fetched_at, created_at, updated_at) "
                "VALUES ('garmin', ?, ?, 'active', 1, 'provider_reported', 'garmin', ?, "
                "'indoor', ?, 'unknown', ?, ?, ?)",
                (provider_id, activity_id, sport, STAMP, STAMP, STAMP, STAMP),
            )

    def strength(self, weight: float = 80.0) -> ActivityStrengthSetSet:
        return ActivityStrengthSetSet(
            provider_activity_id=ID,
            provenance=GARMIN_PROVENANCE,
            origin=ActivityDetailOrigin.FETCH,
            source=StrengthSetSource.GARMIN_EXERCISE_SETS,
            sets=(
                ActivityStrengthSet(
                    index=0,
                    set_type=StrengthSetType.ACTIVE,
                    exercise_category=ExerciseCategory.DEADLIFT,
                    exercise_name="BARBELL_DEADLIFT",
                    reps=5,
                    weight_kg=weight,
                    duration_s=20.0,
                    start_offset_s=12.0,
                    workout_step_index=2,
                ),
                ActivityStrengthSet(
                    index=1, set_type=StrengthSetType.REST, duration_s=120.0
                ),
            ),
        )

    def store(self, detail: ActivityStrengthSetSet) -> WriteOutcome:
        return replace_detail_set(
            self.db, detail, mapper_version=4, summary_sha256="b" * 64, now=STAMP
        )

    def test_round_trip_keeps_every_set_value_and_the_source(self) -> None:
        self.assertEqual(self.store(self.strength()), WriteOutcome.WRITTEN)
        (stored,) = detail_sets_for(self.db, "garmin", ID)
        self.assertEqual(stored.detail, self.strength())
        self.assertEqual(self.store(self.strength()), WriteOutcome.UNCHANGED)
        self.assertEqual(self.store(self.strength(weight=85.0)), WriteOutcome.UPDATED)
        (updated,) = detail_sets_for(self.db, "garmin", ID)
        self.assertIsInstance(updated.detail, ActivityStrengthSetSet)
        assert isinstance(updated.detail, ActivityStrengthSetSet)
        self.assertEqual(updated.detail.sets[0].weight_kg, 85.0)
        self.assertEqual(
            len(
                self.db.execute(
                    "SELECT set_index FROM activity_strength_sets"
                ).fetchall()
            ),
            2,
        )

    def test_the_schema_requires_the_set_source_for_strength_sets_only(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
                "detail_kind, mapper_version, origin, source_kind, recorded_by, "
                "content_sha256, fetched_at, created_at, updated_at) VALUES "
                "('garmin', ?, 'strength_sets', 1, 'fetch', 'provider_reported', "
                "'garmin', ?, ?, ?, ?)",
                (ID, "c" * 64, STAMP, STAMP, STAMP),
            )

    def test_strength_record_ids_selects_strength_records_only(self) -> None:
        self.assertEqual(strength_record_ids(self.db, "garmin", [ID, "222", "x"]), {ID})
        self.assertEqual(strength_record_ids(self.db, "garmin", []), set())

    def test_rejected_values_never_reach_the_table(self) -> None:
        invalid = (
            {"weight_kg": 0.0},
            {"exercise_name": "back squat"},
            {"reps": -1},
            {"index": 500},
        )
        for overrides in invalid:
            values: dict[str, Any] = {
                "index": 0,
                "set_type": StrengthSetType.ACTIVE,
                **overrides,
            }
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                ActivityStrengthSet(**values)
        with self.assertRaises(ValueError):
            ActivityStrengthSetSet(
                provider_activity_id=ID,
                provenance=GARMIN_PROVENANCE,
                origin=ActivityDetailOrigin.FETCH,
                source=StrengthSetSource.FIT_SET_MESSAGES,
                sets=(ActivityStrengthSet(index=1, set_type=StrengthSetType.ACTIVE),),
            )


class ExerciseSetFetchTests(unittest.TestCase):
    class Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_activity_details(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls.append("details")
            return {}

        def get_activity_exercise_sets(self, activity_id: str) -> Any:
            self.calls.append("exercise_sets")
            return {"activityId": activity_id, "exerciseSets": []}

    def collect(self, client: Any, **kwargs: Any) -> dict[str, Any]:
        def external_call(
            _provider: str, capability: str, fetch: Any, _details: Any
        ) -> Any:
            if capability in kwargs.get("paused", ()):
                raise AssertionError("a paused part must not be called")
            return fetch()

        return collect_garmin_activity_detail(
            client,
            ID,
            external_call=external_call,
            redact=str,
            capability_allowed=lambda capability: (
                capability not in kwargs.get("paused", ())
            ),
            exercise_sets=kwargs.get("exercise_sets", False),
        )

    def test_exercise_sets_are_requested_for_strength_activities_only(self) -> None:
        client = self.Client()
        self.assertNotIn("exercise_sets", self.collect(client))
        self.assertEqual(client.calls, ["details"])
        client = self.Client()
        collected = self.collect(client, exercise_sets=True)
        self.assertEqual(
            collected["exercise_sets"], {"activityId": ID, "exerciseSets": []}
        )
        self.assertEqual(client.calls, ["details", "exercise_sets"])

    def test_a_paused_exercise_set_capability_skips_only_that_part(self) -> None:
        client = self.Client()
        collected = self.collect(
            client, exercise_sets=True, paused=("activity_exercise_sets",)
        )
        self.assertEqual(client.calls, ["details"])
        self.assertEqual(collected["skipped"], ["activity_exercise_sets"])
        self.assertIn("details", collected)

    def test_a_transport_without_the_sdk_method_leaves_the_part_absent(self) -> None:
        class PersonalOnly:
            def get_activity_details(self, *_args: Any, **_kwargs: Any) -> Any:
                return {}

        collected = self.collect(PersonalOnly(), exercise_sets=True)
        self.assertNotIn("exercise_sets", collected)
        self.assertNotIn("errors", collected)

    def test_lap_sets_are_unaffected_by_set_messages(self) -> None:
        # The set list is its own kind; laps and streams keep their own sets.
        result = map_fit_activity_detail(
            _fit(SQUAT_SETS), provider_activity_id=ID, provenance=GARMIN_PROVENANCE
        )
        self.assertFalse(any(isinstance(r, ActivityLapSet) for r in result.records))


class ReviewRegressionTests(StrengthSetStoreTests):
    """Limits and precedence found in review of the first slice."""

    def test_more_than_500_sets_are_capped_without_raising(self) -> None:
        many = [_set(set_type=1, reps=3) for _ in range(502)]
        result = map_fit_activity_detail(
            _fit(many), provider_activity_id=ID, provenance=GARMIN_PROVENANCE
        )
        self.assertEqual(len(_strength(result).sets), 500)
        self.assertIn(MappingIssue(ID, "set", IssueReason.OUT_OF_RANGE), result.issues)
        payload = {"exerciseSets": [{"setType": "ACTIVE"}] * 501}
        garmin = map_garmin_activity_detail(
            {"activity_id": ID, "exercise_sets": payload},
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED,
        )
        self.assertEqual(len(_strength(garmin).sets), 500)
        self.assertIn(
            MappingIssue(ID, "exerciseSets", IssueReason.OUT_OF_RANGE), garmin.issues
        )

    def test_file_issues_are_dropped_when_exercise_sets_win(self) -> None:
        broken_file = _fit([_set(reps=5), _set(set_type=1, reps=6)])
        result = map_garmin_activity_detail(
            {"activity_id": ID, "exercise_sets": _exercise_sets(), "fit": broken_file},
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED,
        )
        self.assertEqual(result.issues, ())
        file_only = map_garmin_activity_detail(
            {"activity_id": ID, "fit": broken_file},
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED,
        )
        self.assertIn(
            MappingIssue(ID, "set_type", IssueReason.MISSING), file_only.issues
        )

    def test_stored_exercise_sets_are_kept_and_restamped_over_file_sets(self) -> None:
        self.store(self.strength())
        file_sets = ActivityStrengthSetSet(
            provider_activity_id=ID,
            provenance=GARMIN_PROVENANCE,
            origin=ActivityDetailOrigin.FETCH,
            source=StrengthSetSource.FIT_SET_MESSAGES,
            sets=(
                ActivityStrengthSet(index=0, set_type=StrengthSetType.ACTIVE, reps=4),
            ),
        )
        self.assertTrue(_keeps_corrected_sets(self.db, ID, file_sets))
        self.assertFalse(_keeps_corrected_sets(self.db, ID, self.strength()))
        self.assertFalse(_keeps_corrected_sets(self.db, "222", file_sets))
        restamp_detail_set(
            self.db,
            "garmin",
            ID,
            ActivityDetailKind.STRENGTH_SETS,
            summary_sha256="e" * 64,
            fetched_at=STAMP,
        )
        (stored,) = detail_sets_for(self.db, "garmin", ID)
        assert isinstance(stored.detail, ActivityStrengthSetSet)
        self.assertEqual(stored.detail.sets, self.strength().sets)
        self.assertEqual(stored.summary_sha256, "e" * 64)
        self.assertEqual(stored.fetched_at, STAMP)
        self.assertEqual(
            stored_strength_source(self.db, "garmin", ID),
            StrengthSetSource.GARMIN_EXERCISE_SETS.value,
        )

    def test_other_kinds_keep_their_content_hash_header(self) -> None:
        laps = ActivityLapSet(
            provider_activity_id=ID,
            provenance=GARMIN_PROVENANCE,
            origin=ActivityDetailOrigin.FETCH,
            lap_source=LapSource.DEVICE_LAPS,
            laps=(ActivityLap(0, LapKind.LAP, 0.0, 60.0),),
        )
        self.assertNotIn("set_source", _header(laps, 4))
        self.assertEqual(
            _header(self.strength(), 4)["set_source"], "garmin_exercise_sets"
        )


if __name__ == "__main__":
    unittest.main()
