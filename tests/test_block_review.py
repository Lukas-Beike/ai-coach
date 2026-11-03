"""Training block review projection, lessons, Coach tool contract and read-only scope."""

import inspect
import unittest
from datetime import date
from unittest.mock import Mock

from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.errors import AppError
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.report_service import (
    TrainingReportReadService,
    TrainingReportServices,
)
from backend.planning import block_review as block_review_module
from backend.planning.block_review import block_lessons, block_review
from backend.planning.plan_guard_service import build_planning_brief
from backend.planning.season_preparation import load_scenarios
from tests.test_training_report import (
    _empty_season_source,
    _FakeDatabaseManager,
    _Rows,
    _summary,
)
from tests.test_weekly_progress import _EmptyReader, _zones

TODAY = date(2026, 10, 2)  # default block: 2026-08-31 to 2026-09-27


def _unit(day, sport="run", status="completed", focus=None, duration=3600):
    row = {
        "date": day,
        "starts_at_local": f"{day}T07:00:00",
        "sport": sport,
        "compliance": {"status": status, "planned_duration": duration},
    }
    if focus:
        row["session_focus"] = focus
    return row


def _service(rows=(), plan=None, checkins=(), feedback=(), model="pyramidal"):
    return TrainingReportReadService(
        read_synced_at=lambda _db: None,
        read_plan=lambda: plan,
        read_checkins=lambda: list(checkins),
        read_feedback=lambda: list(feedback),
        today=lambda: TODAY,
        load_scenarios=load_scenarios,
        season_source=_empty_season_source(),
        canonical=CanonicalPerformanceSource(
            database_manager=_FakeDatabaseManager,
            observation_reader=_EmptyReader,
            activity_summaries=lambda: _Rows(rows),
        ),
        curve_records=list,
        session_feedback=lambda keys: [],
        training_model=lambda: model,
        review_block=block_review,
    )


def _run(key, day, **values):
    return _summary(key, day, sport="run", moving_duration_s=3600, **values)


class BlockReviewTests(unittest.TestCase):
    def test_complete_block_compares_plan_with_records(self):
        zones = _zones(3000, 300, 300)
        rows = [
            _run("a", "2026-09-01", heart_rate_zone_times=zones),
            _run("b", "2026-09-08", heart_rate_zone_times=zones),
            _run("c", "2026-09-19", heart_rate_zone_times=zones),
        ]
        plan = {
            "training_calendar": [
                _unit("2026-09-01"),
                _unit("2026-09-08", focus="threshold"),
                _unit("2026-09-19", focus="long"),
            ]
        }
        review = _service(rows, plan).block_review({}, "UTC")
        self.assertEqual("block-review-v1", review["method"])
        self.assertEqual(("2026-08-31", "2026-09-27"), (review["start"], review["end"]))
        self.assertEqual(
            {"planned": 3, "completed": 3, "missed": 0}, review["compliance"]
        )
        run = review["volume"]["run"]
        self.assertEqual(3, run["planned"])
        self.assertEqual(10800, run["planned_duration_s"])
        self.assertEqual(3, run["completed_sessions"])
        self.assertEqual(10800, run["completed_duration_s"])
        self.assertEqual(
            {"completed": 1, "missed": 0, "planned": 1},
            review["key_sessions"]["by_focus"]["threshold"],
        )
        self.assertEqual(3, review["intensity"]["measured_sessions"])
        self.assertEqual([], review["lessons"])
        self.assertIn("pace_at_heart_rate", review["performance"]["not_covered"])
        self.assertIn("no causal claim", review["coverage_note"])

    def test_partly_missed_block_yields_lessons(self):
        plan = {
            "training_calendar": [
                _unit("2026-09-01", focus="long", status="missed"),
                _unit("2026-09-02", focus="long", status="missed"),
                _unit("2026-09-05", focus="long"),
                _unit("2026-09-08", status="missed"),
                _unit("2026-09-09", status="missed"),
                _unit("2026-09-12"),
                _unit("2026-09-30", status="planned"),
            ]
        }
        review = _service([_run("a", "2026-09-05")], plan).block_review({}, "UTC")
        self.assertEqual(
            {"planned": 6, "completed": 2, "missed": 4}, review["compliance"]
        )
        self.assertEqual(
            {"planned": 2, "completed": 0, "missed": 2},
            review["key_sessions"]["long_weekday"],
        )
        codes = [item["code"] for item in review["lessons"]]
        self.assertEqual(["low_compliance", "long_weekday_missed"], codes)

    def test_block_without_performance_data_stays_unknown(self):
        review = _service().block_review({}, "UTC")
        self.assertFalse(review["plan_available"])
        self.assertEqual(0, review["compliance"]["planned"])
        self.assertIsNone(review["intensity"]["shares"])
        self.assertEqual("insufficient_data", review["performance"]["eftp"]["status"])
        self.assertEqual([], review["lessons"])
        self.assertEqual(0, review["subjective"]["checkin_scores"]["checkins"])

    def test_subjective_signals_and_notes(self):
        checkins = [
            {"checkin_date": f"2026-09-{day:02d}", "soreness": score}
            for day, score in zip(range(1, 9), (2, 2, 2, 2, 5, 5, 5, 5))
        ]
        rows = [_run("a", "2026-09-05")]
        feedback = [{"activity_id": "a", "notes": "zu hart " * 100, "session_rpe": 9}]
        review = _service(rows, None, checkins, feedback).block_review({}, "UTC")
        scores = review["subjective"]["checkin_scores"]["soreness"]
        self.assertEqual((2.0, 5.0), (scores["earlier_mean"], scores["later_mean"]))
        self.assertEqual(["soreness_rising"], [i["code"] for i in review["lessons"]])
        (note,) = review["subjective"]["feedback_notes"]
        self.assertLessEqual(len(note["notes"]), 200)
        self.assertIn("untrusted", review["subjective"]["notes_source"])

    def test_rising_session_rpe_lesson(self):
        def week(start, per_session):
            load = {"value": per_session * 2, "rated_sessions": 2}
            return {
                "week_start": start,
                "sports": {"all": {"session_rpe_load": load}},
            }

        weeks = [
            week("2026-09-07", 200),
            week("2026-09-14", 220),
            week("2026-09-21", 260),
        ]
        review = {
            "compliance": {"planned": 0, "completed": 0, "missed": 0},
            "key_sessions": {"long_weekday": {"planned": 0, "completed": 0}},
            "intensity": {"deviating_bands": {}},
            "subjective": {
                "session_rpe_weeks": block_review_module._rpe_weeks(
                    {"week_list": weeks}
                ),
                "checkin_scores": {
                    field: {"earlier_n": 0, "later_n": 0}
                    for field in block_review_module.SCORE_FIELDS
                },
            },
        }
        (lesson,) = block_lessons(review)
        self.assertEqual("rpe_rising", lesson["code"])
        self.assertEqual("limited", lesson["evidence_strength"])

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(AppError):
            _service().block_review({"start": "2026-08-31", "days": 30}, "UTC")

    def test_projection_has_no_write_path(self):
        source = inspect.getsource(block_review_module)
        for token in ("writer", "execute(", "INSERT", "UPDATE ", "DELETE", "requests"):
            self.assertNotIn(token, source)


class BlockReviewToolAndBriefTests(unittest.TestCase):
    def _tool(self):
        reports = TrainingReportServices(
            records=Mock(),
            profiles=Mock(),
            report=_service(),
            derived=Mock(),
            season=Mock(),
            timezone=lambda: "UTC",
        )
        return CoachActivityReadToolService(
            Mock(), Mock(), Mock(), lambda: TODAY, reports
        )

    def test_section_runs_alone(self):
        result = self._tool().execute(
            "get_training_report", {"sections": ["block_review"]}
        )
        self.assertEqual("block-review-v1", result["block_review"]["method"])
        with self.assertRaises(AppError):
            self._tool().execute(
                "get_training_report", {"sections": ["block_review", "report"]}
            )

    def test_brief_carries_labelled_lessons(self):
        lessons = [
            {"code": "x", "text": "t", "evidence_strength": "limited", "basis": {}}
        ]
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=TODAY,
            lessons=lessons,
        )
        self.assertEqual(
            [{"code": "x", "text": "t", "evidence_strength": "limited"}],
            brief["lessons"]["items"],
        )
        self.assertIn("descriptive", brief["lessons"]["source"])
        empty = build_planning_brief(
            progress={}, completed=[], competitions=[], training_model="", today=TODAY
        )
        self.assertEqual([], empty["lessons"]["items"])


if __name__ == "__main__":
    unittest.main()
