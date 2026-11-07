"""Consumers of executed strength sets: summary, plan comparison and checks.

Synthetic stored sets in a temporary database; no provider data or accounts.
Planned exercises carry a stored Garmin pair, so no catalogue is needed.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.activities.calendar_projection import workout_compliance
from backend.activities.strength_sets import (
    plan_comparison,
    select_strength_sets,
    strength_summaries,
    strength_summary,
    with_strength_summaries,
)
from backend.canonical.activity_detail import (
    ActivityStrengthSet,
    ActivityStrengthSetSet,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ExerciseCategory,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StrengthSetSource,
    StrengthSetType,
)
from backend.coach.activity_read_tools import _strength_plan
from backend.db import row_factory
from backend.db.activity_detail_store import StoredDetailSet, replace_detail_set
from backend.db.schema import initialize_schema
from backend.planning.leg_strength import classify, completed_unit
from backend.planning.strength_progress import strength_progress

STAMP = "2026-11-07T08:00:00+00:00"
ACTIVE = StrengthSetType.ACTIVE
REST = StrengthSetType.REST
SQUAT = ExerciseCategory.SQUAT
BENCH = ExerciseCategory.BENCH_PRESS


def provenance(provider: ProviderId = ProviderId.GARMIN) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=datetime(2026, 11, 7, 7, 0, tzinfo=UTC),
        label=None,
    )


def set_list(
    rows: list[tuple[Any, ...]],
    *,
    source: StrengthSetSource = StrengthSetSource.GARMIN_EXERCISE_SETS,
    provider: ProviderId = ProviderId.GARMIN,
    activity: str = "g1",
) -> ActivityStrengthSetSet:
    """Rows are (type, category, name, reps, kg, duration)."""
    return ActivityStrengthSetSet(
        provider_activity_id=activity,
        provenance=provenance(provider),
        origin=ActivityDetailOrigin.FETCH,
        source=source,
        sets=tuple(
            ActivityStrengthSet(
                index=index,
                set_type=kind,
                exercise_category=category,
                exercise_name=name,
                reps=reps,
                weight_kg=kg,
                duration_s=duration,
            )
            for index, (kind, category, name, reps, kg, duration) in enumerate(rows)
        ),
    )


def stored(detail: ActivityStrengthSetSet, provider: str = "garmin") -> StoredDetailSet:
    return StoredDetailSet(
        provider=provider,
        provider_activity_id=detail.provider_activity_id,
        activity_id="act_1",
        mapper_version=4,
        summary_sha256=None,
        fetched_at=STAMP,
        detail=detail,
    )


SQUAT_SESSION = [
    (ACTIVE, SQUAT, "BARBELL_BACK_SQUAT", 5, 80.0, 30.0),
    (REST, None, None, None, None, 120.0),
    (ACTIVE, SQUAT, "BARBELL_BACK_SQUAT", 5, 82.5, 31.0),
    (REST, None, None, None, None, 125.0),
    (ACTIVE, SQUAT, "BARBELL_BACK_SQUAT", 3, 82.5, 25.0),
    (ACTIVE, BENCH, "BARBELL_BENCH_PRESS", 8, 60.0, 40.0),
    (ACTIVE, BENCH, "BARBELL_BENCH_PRESS", 8, 60.0, 40.0),
]


def planned(
    name: str,
    category: str,
    exercise: str,
    sets: int,
    reps: int,
    kg: float | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "sets": sets,
        "reps": reps,
        "garmin_exercise": name,
        "garmin_pair": {"category": category, "exercise": exercise},
    }
    if kg is not None:
        item["kg"] = kg
    return item


class StrengthSummaryTests(unittest.TestCase):
    def test_summary_groups_exercises_with_rest_top_set_and_volume(self) -> None:
        summary = strength_summary(stored(set_list(SQUAT_SESSION)), set_list=True)
        self.assertEqual(summary["active_sets"], 5)
        self.assertEqual(summary["total_reps"], 29)
        self.assertEqual(
            summary["volume_kg"], round(5 * 80 + 5 * 82.5 + 3 * 82.5 + 16 * 60, 1)
        )
        self.assertTrue(summary["leg"])
        squat, bench = summary["exercises"]
        self.assertEqual(
            {
                key: squat[key]
                for key in (
                    "category",
                    "name",
                    "leg",
                    "sets",
                    "reps",
                    "top_kg",
                    "top_reps",
                )
            },
            {
                "category": "squat",
                "name": "BARBELL_BACK_SQUAT",
                "leg": True,
                "sets": 3,
                "reps": [5, 5, 3],
                "top_kg": 82.5,
                "top_reps": 5,
            },
        )
        self.assertEqual([s.get("rest_s") for s in squat["set_list"]], [120, 125, None])
        self.assertFalse(bench["leg"])
        compact = strength_summary(stored(set_list(SQUAT_SESSION)), set_list=False)
        self.assertNotIn("set_list", compact["exercises"][0])

    def test_leg_is_false_only_when_every_exercise_is_known(self) -> None:
        upper = set_list([(ACTIVE, BENCH, None, 8, 60.0, None)])
        self.assertIs(strength_summary(stored(upper), set_list=False)["leg"], False)
        unknown = set_list(
            [(ACTIVE, BENCH, None, 8, 60.0, None), (ACTIVE, None, None, 8, None, None)]
        )
        self.assertIsNone(strength_summary(stored(unknown), set_list=False)["leg"])

    def test_exercise_sets_win_over_file_sets_and_garmin_over_others(self) -> None:
        file_sets = stored(
            set_list(SQUAT_SESSION, source=StrengthSetSource.FIT_SET_MESSAGES)
        )
        wahoo = stored(
            set_list(
                SQUAT_SESSION,
                source=StrengthSetSource.FIT_SET_MESSAGES,
                provider=ProviderId.WAHOO,
                activity="w1",
            ),
            provider="wahoo",
        )
        corrected = stored(set_list(SQUAT_SESSION))
        self.assertIs(select_strength_sets([wahoo, file_sets, corrected]), corrected)
        self.assertIs(select_strength_sets([wahoo, file_sets]), file_sets)
        self.assertIsNone(select_strength_sets([]))


class PlanComparisonTests(unittest.TestCase):
    def summary(self) -> dict[str, Any]:
        return strength_summary(stored(set_list(SQUAT_SESSION)), set_list=False)

    def test_completed_sets_count_planned_reps_and_unknowns_are_no_miss(self) -> None:
        structure = [
            planned("Barbell Back Squat", "SQUAT", "BARBELL_BACK_SQUAT", 4, 5, 82.5),
            planned("Barbell Bench Press", "BENCH_PRESS", "BARBELL_BENCH_PRESS", 3, 8),
            {"name": "Mystery move", "sets": 3, "reps": 10},
        ]
        comparison = plan_comparison(structure, self.summary())
        assert comparison is not None
        # Squat: 4 planned, 3 done, 2 at 5 reps; bench: 3 planned, 2 done at 8.
        self.assertEqual(
            (comparison["planned_sets"], comparison["completed_sets"]), (7, 4)
        )
        self.assertEqual(comparison["percentage"], 57)
        squat, bench, mystery = comparison["exercises"]
        self.assertEqual(
            (squat["done_sets"], squat["completed_sets"], squat["reps"]),
            (3, 2, [5, 5, 3]),
        )
        self.assertEqual(squat["planned_kg"], 82.5)
        self.assertEqual(bench["completed_sets"], 2)
        self.assertEqual(mystery["status"], "unknown")

    def test_twelve_planned_and_nine_done_is_75_percent(self) -> None:
        rows = [(ACTIVE, SQUAT, None, 5, 80.0, None)] * 9
        summary = strength_summary(stored(set_list(rows)), set_list=False)
        structure = [
            planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 6, 5),
            planned("Front", "SQUAT", "BARBELL_FRONT_SQUAT", 6, 5),
        ]
        comparison = plan_comparison(structure, summary)
        assert comparison is not None
        self.assertEqual(comparison["percentage"], 75)
        self.assertEqual([row["done_sets"] for row in comparison["exercises"]], [6, 3])

    def test_no_usable_side_gives_no_comparison(self) -> None:
        self.assertIsNone(plan_comparison([], self.summary()))
        no_categories = strength_summary(
            stored(set_list([(ACTIVE, None, None, 5, 80.0, None)])), set_list=False
        )
        self.assertIsNone(
            plan_comparison([planned("Squat", "SQUAT", "X", 3, 5)], no_categories)
        )


class ComplianceAndLegTests(unittest.TestCase):
    def activity(self) -> dict[str, Any]:
        return {
            "id": "act_1",
            "sport": "strength",
            "name": "Gym",
            "started_at_local": "2026-11-05T18:00:00",
            "moving_duration_s": 2700,
            "strength_sets": strength_summary(
                stored(set_list(SQUAT_SESSION)), set_list=False
            ),
        }

    def event(self, **extra: Any) -> dict[str, Any]:
        return {
            "id": "u1",
            "starts_at_local": "2026-11-05T18:00:00",
            "sport": "strength",
            "planned_duration_s": 2700,
            **extra,
        }

    def test_strength_basis_replaces_duration_when_both_sides_exist(self) -> None:
        structure = [planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 3, 5)]
        result = workout_compliance(
            self.event(strength_structure=structure), self.activity(), date(2026, 11, 7)
        )
        self.assertEqual(result["basis"], "strength_sets")
        self.assertEqual(result["percentage"], 67)
        self.assertEqual((result["planned_value"], result["actual_value"]), (3, 2))
        self.assertEqual(result["strength_sets"]["exercises"][0]["status"], "matched")

    def test_without_sets_or_structure_the_old_basis_stays(self) -> None:
        plain = workout_compliance(self.event(), self.activity(), date(2026, 11, 7))
        self.assertEqual(plain["basis"], "duration")
        self.assertNotIn("strength_sets", plain)
        activity = {
            key: value
            for key, value in self.activity().items()
            if key != "strength_sets"
        }
        structure = [planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 3, 5)]
        result = workout_compliance(
            self.event(strength_structure=structure), activity, date(2026, 11, 7)
        )
        self.assertEqual(result["basis"], "duration")

    def test_a_squat_session_without_leg_words_is_leg_strength(self) -> None:
        found = classify(completed_unit(self.activity()))
        assert found is not None
        self.assertTrue(found.leg)
        upper = dict(self.activity(), name="Beintag", strength_sets={"leg": False})
        found = classify(completed_unit(upper))
        assert found is not None
        self.assertFalse(found.leg)
        keyword = dict(self.activity(), name="Beintag", strength_sets=None)
        found = classify(completed_unit(keyword))
        assert found is not None
        self.assertTrue(found.leg)


class ProgressionTests(unittest.TestCase):
    def test_top_sets_per_exercise_newest_first(self) -> None:
        rows = []
        for day, kg in (
            ("2026-11-01", 80.0),
            ("2026-11-04", 82.5),
            ("2026-10-28", 77.5),
        ):
            rows.append(
                {
                    "started_at_local": f"{day}T18:00:00",
                    "strength_sets": strength_summary(
                        stored(
                            set_list(
                                [(ACTIVE, SQUAT, "BARBELL_BACK_SQUAT", 5, kg, None)] * 3
                            )
                        ),
                        set_list=False,
                    ),
                }
            )
        rows.append({"started_at_local": "2026-11-05T07:00:00", "sport": "run"})
        progress = strength_progress(rows)
        (squat,) = progress["exercises"]
        self.assertEqual(squat["exercise"], "BARBELL_BACK_SQUAT")
        self.assertEqual(
            [
                (s["date"], s["top_kg"], s["top_reps"], s["sets"])
                for s in squat["sessions"]
            ],
            [
                ("2026-11-04", 82.5, 5, 3),
                ("2026-11-01", 80.0, 5, 3),
                ("2026-10-28", 77.5, 5, 3),
            ],
        )


class SessionReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")
        for activity_id, provider_id, state, merged in (
            ("act_1", "g1", "active", None),
            ("act_2", "g2", "duplicate", "act_1"),
            ("act_3", "g3", "deleted", None),
        ):
            self.db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, state, merged_into, started_at, created_at, updated_at) "
                "VALUES (?, 'garmin', ?, ?, ?, ?, ?, ?)",
                (activity_id, provider_id, state, merged, STAMP, STAMP, STAMP),
            )
            self.db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, activity_id, state, "
                "mapper_version, source_kind, recorded_by, sport, environment, started_at, load_model, "
                "fetched_at, created_at, updated_at) VALUES ('garmin', ?, ?, 'active', 1, "
                "'provider_reported', 'garmin', 'strength', 'indoor', ?, 'unknown', ?, ?, ?)",
                (provider_id, activity_id, STAMP, STAMP, STAMP, STAMP),
            )

    def test_merged_lists_belong_to_the_survivor_and_deleted_ones_are_skipped(
        self,
    ) -> None:
        replace_detail_set(
            self.db,
            set_list(
                SQUAT_SESSION, source=StrengthSetSource.FIT_SET_MESSAGES, activity="g1"
            ),
            mapper_version=3,
            summary_sha256=None,
            now=STAMP,
        )
        replace_detail_set(
            self.db,
            set_list(SQUAT_SESSION, activity="g2"),
            mapper_version=4,
            summary_sha256=None,
            now=STAMP,
        )
        replace_detail_set(
            self.db,
            set_list(SQUAT_SESSION, activity="g3"),
            mapper_version=4,
            summary_sha256=None,
            now=STAMP,
        )
        summaries = strength_summaries(self.db, ["act_1", "act_3"])
        self.assertEqual(set(summaries), {"act_1"})
        self.assertEqual(summaries["act_1"]["source"], "garmin_exercise_sets")
        many = strength_summaries(
            self.db, ["act_1", *(f"act_x{i}" for i in range(1200))]
        )
        self.assertEqual(set(many), {"act_1"})
        merged = with_strength_summaries([{"id": "act_1"}, {"id": "act_9"}], summaries)
        self.assertIn("strength_sets", merged[0])
        self.assertNotIn("strength_sets", merged[1])


class ReviewRegressionTests(unittest.TestCase):
    """Unrecognized exercises, supersets and long histories (review of PR 2)."""

    def test_unrecognized_sets_decide_neither_leg_nor_a_miss(self) -> None:
        other = ExerciseCategory.OTHER
        rows = [(ACTIVE, other, "UNKNOWN", 5, 80.0, None)] * 6
        summary = strength_summary(stored(set_list(rows)), set_list=False)
        self.assertIsNone(summary["leg"])
        self.assertEqual(summary["unrecognized_sets"], 6)
        structure = [planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 3, 5)]
        self.assertIsNone(plan_comparison(structure, summary))
        mixed = strength_summary(
            stored(set_list([*rows, (ACTIVE, BENCH, None, 8, 60.0, None)])),
            set_list=False,
        )
        comparison = plan_comparison(
            [*structure, planned("Bench", "BENCH_PRESS", "BARBELL_BENCH_PRESS", 1, 8)],
            mixed,
        )
        assert comparison is not None
        # The squat may hide in the unrecognized sets: unknown, not missed.
        self.assertEqual(
            [row["status"] for row in comparison["exercises"]], ["unknown", "matched"]
        )
        self.assertEqual(comparison["percentage"], 100)

    def test_total_body_is_leg_and_neutral_categories_decide_nothing(self) -> None:
        total = set_list([(ACTIVE, ExerciseCategory.TOTAL_BODY, None, 10, None, None)])
        self.assertTrue(strength_summary(stored(total), set_list=False)["leg"])
        cardio_and_bench = set_list(
            [
                (ACTIVE, ExerciseCategory.CARDIO, None, None, None, 300.0),
                (ACTIVE, BENCH, None, 8, 60.0, None),
            ]
        )
        self.assertIs(
            strength_summary(stored(cardio_and_bench), set_list=False)["leg"], False
        )

    def test_superset_sets_group_per_exercise_over_the_session(self) -> None:
        row = ExerciseCategory.ROW
        rows = []
        for kg in (40.0, 80.0, 80.0):
            rows += [
                (ACTIVE, BENCH, "BARBELL_BENCH_PRESS", 5, kg, None),
                (ACTIVE, row, "BENT_OVER_ROW", 8, 50.0, None),
            ]
        summary = strength_summary(stored(set_list(rows)), set_list=True)
        bench, rowing = summary["exercises"]
        self.assertEqual(
            (bench["sets"], bench["top_kg"], bench["reps"]), (3, 80.0, [5, 5, 5])
        )
        self.assertEqual(rowing["sets"], 3)
        progress = strength_progress(
            [{"started_at_local": "2026-11-05T18:00:00", "strength_sets": summary}]
        )
        self.assertEqual(progress["exercises"][0]["sessions"][0]["top_kg"], 80.0)

    def test_the_comparison_uses_every_set_beyond_the_display_limit(self) -> None:
        rows = [(ACTIVE, SQUAT, f"SQUAT_{index}", 5, 60.0, None) for index in range(25)]
        summary = strength_summary(stored(set_list(rows)), set_list=False)
        self.assertEqual(len(summary["exercises"]), 20)
        self.assertEqual(summary["omitted_exercises"], 5)
        comparison = plan_comparison(
            [planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 25, 5)], summary
        )
        assert comparison is not None
        self.assertEqual(comparison["percentage"], 100)


class CoachStrengthPlanTests(unittest.TestCase):
    def test_the_matched_unit_structure_is_compared(self) -> None:
        detail = {
            "strength_sets": strength_summary(
                stored(set_list(SQUAT_SESSION)), set_list=True
            )
        }
        session = {"sport": "strength", "started_at_local": "2026-11-05T18:00:00"}
        unit = {
            "id": "u1",
            "date": "2026-11-05",
            "sport": "strength",
            "strength_structure": [
                planned("Squat", "SQUAT", "BARBELL_BACK_SQUAT", 3, 5)
            ],
        }
        result = _strength_plan(detail, session, None, [unit])
        assert result is not None
        self.assertEqual((result["planned_unit_id"], result["percentage"]), ("u1", 67))
        self.assertIsNone(
            _strength_plan(detail, {**session, "sport": "run"}, None, [unit])
        )
        self.assertIsNone(_strength_plan({}, session, None, [unit]))


if __name__ == "__main__":
    unittest.main()
