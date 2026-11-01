"""Session-RPE load (M1, gate G3): values, sums, sources, edits, undo, duplicates.

Unit cases build neutral activity summaries directly. Integration cases use the
two-provider ride of ``test_feedback_session_identity`` (Intervals.icu with
``icu_rpe`` 7 plus its Garmin copy, one canonical session) with the real
feedback service, change history undo and canonical summaries. Temporary
database and synthetic rows only.
"""

from __future__ import annotations

import copy
import unittest
from datetime import date
from typing import Any

import test_feedback_history as history
from test_feedback_session_identity import (
    GARMIN_ID,
    INTERVALS_ID,
    ZONE,
    FeedbackSessionFixture,
)

from backend.activities.activity_summary import activity_summaries
from backend.performance.session_rpe_load import (
    REASON_CONFLICTING_PROVIDER_RATINGS,
    REASON_INVALID_DURATION,
    REASON_NO_ELAPSED_DURATION,
    REASON_NO_RATING,
    feedback_by_session,
    session_load,
    session_rpe_load,
)
from backend.performance.training_report import training_report
from backend.sync.canonical_table_reader import CanonicalTableReader

DAY = "2026-10-21"


def summary(
    activity_id: str, minutes: float | None = 60, day: str = DAY, **fields: Any
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": activity_id,
        "started_at": f"{day}T07:00:00+00:00",
        "started_at_local": f"{day}T09:00:00",
        "sport": "ride",
        "name": "Synthetic ride",
        "sources": {},
        "record_ids": {},
    }
    if minutes is not None:
        value["elapsed_duration_s"] = minutes * 60
    value.update(fields)
    return value


def provider_rpe(rpe: float) -> dict[str, Any]:
    return {"rpe": rpe, "sources": {"rpe": "Intervals.icu"}}


def report(
    summaries: list[dict[str, Any]],
    feedback: dict[str, dict[str, Any]],
    start: str = DAY,
    end: str = DAY,
) -> dict[str, Any]:
    return session_rpe_load(
        summaries,  # type: ignore[arg-type]
        feedback,
        start=date.fromisoformat(start),
        end=date.fromisoformat(end),
        timezone="UTC",
    )


class SessionLoadTests(unittest.TestCase):
    def test_minutes_times_local_rpe_in_arbitrary_units(self) -> None:
        entry, value = session_load(summary("a"), {"session_rpe": 5})
        self.assertEqual((value, entry["value"]), (300.0, 300.0))
        self.assertEqual(
            (entry["rpe"], entry["rpe_source"], entry["rpe_source_label"]),
            (5.0, "athlete_feedback", "Athletenfeedback"),
        )
        self.assertEqual(
            (entry["duration_min"], entry["status"]), (60.0, "descriptive")
        )

    def test_rpe_zero_is_zero_load_and_a_missing_rpe_is_unknown(self) -> None:
        self.assertEqual(session_load(summary("a", 30), {"session_rpe": 0})[1], 0.0)
        entry, value = session_load(summary("b"), {"session_rpe": None, "notes": "x"})
        self.assertIsNone(value)
        self.assertEqual(
            (entry["value"], entry["reason"], entry["status"]),
            (None, REASON_NO_RATING, "insufficient_data"),
        )
        self.assertEqual(
            session_load(summary("c"), None)[0]["reason"], REASON_NO_RATING
        )

    def test_local_rating_wins_over_the_provider_rating(self) -> None:
        entry, value = session_load(summary("a", **provider_rpe(7)), {"session_rpe": 5})
        self.assertEqual((value, entry["rpe_source"]), (300.0, "athlete_feedback"))

    def test_provider_rating_is_a_labelled_fallback(self) -> None:
        entry, value = session_load(summary("a", 50, **provider_rpe(6)), None)
        self.assertEqual(value, 300.0)
        self.assertEqual(
            (entry["rpe_source"], entry["rpe_source_label"]),
            ("provider", "Intervals.icu"),
        )
        self.assertIsNone(entry["rated_minutes_after_end"])

    def test_disagreeing_provider_ratings_give_no_value_without_a_local_one(
        self,
    ) -> None:
        conflicting = summary("a", **provider_rpe(6), rpe_conflict=True)
        entry, value = session_load(conflicting, None)
        self.assertIsNone(value)
        self.assertEqual(entry["reason"], REASON_CONFLICTING_PROVIDER_RATINGS)
        self.assertEqual(session_load(conflicting, {"session_rpe": 4})[1], 240.0)

    def test_moving_time_is_no_substitute_for_the_elapsed_duration(self) -> None:
        entry, value = session_load(
            summary("a", None, moving_duration_s=3600.0), {"session_rpe": 5}
        )
        self.assertIsNone(value)
        self.assertEqual(
            (entry["reason"], entry["duration_min"]), (REASON_NO_ELAPSED_DURATION, None)
        )
        for minutes in (0, -5):
            with self.subTest(minutes=minutes):
                self.assertEqual(
                    session_load(summary("b", minutes), {"session_rpe": 5})[0][
                        "reason"
                    ],
                    REASON_INVALID_DURATION,
                )

    def test_rating_time_is_counted_from_the_session_end(self) -> None:
        rated = {"session_rpe": 5, "session_rpe_rated_at": f"{DAY}T08:30:00+00:00"}
        self.assertEqual(
            session_load(summary("a"), rated)[0]["rated_minutes_after_end"], 30
        )
        for unknown in (None, "gestern", f"{DAY}T08:30:00"):
            with self.subTest(rated_at=unknown):
                entry = session_load(
                    summary("a"), {**rated, "session_rpe_rated_at": unknown}
                )[0]
                self.assertIsNone(entry["rated_minutes_after_end"])

    def test_values_round_only_for_output(self) -> None:
        entry, value = session_load(summary("a", 47 / 3), {"session_rpe": 5.5})
        self.assertAlmostEqual(value or 0, 47 / 3 * 5.5)
        self.assertEqual(entry["value"], round(47 / 3 * 5.5, 1))


class PeriodSumTests(unittest.TestCase):
    def test_known_partial_sum_keeps_its_session_coverage(self) -> None:
        result = report(
            [summary("a"), summary("b", 24), summary("c")],
            {"a": {"session_rpe": 5}, "b": {"session_rpe": 5}},
        )
        self.assertEqual(
            result["totals"],
            {
                "value": 420.0,
                "rated_sessions": 2,
                "total_sessions": 3,
                "rpe_sources": {"athlete_feedback": 2, "provider": 0},
            },
        )
        self.assertEqual(result["status"], "descriptive")
        self.assertEqual(
            (result["metric_id"], result["method_id"], result["method_version"]),
            ("session_rpe_load", "session-rpe-load", 1),
        )
        self.assertEqual(result["unit"], "AU")
        self.assertTrue(result["evidence_card"].endswith("m1-session-rpe-load.md"))

    def test_sums_count_both_rating_sources(self) -> None:
        result = report(
            [summary("a"), summary("b", 50, **provider_rpe(6))],
            {"a": {"session_rpe": 5}},
        )
        self.assertEqual(result["totals"]["value"], 600.0)
        self.assertEqual(
            result["totals"]["rpe_sources"], {"athlete_feedback": 1, "provider": 1}
        )

    def test_days_weeks_and_sports_cover_the_whole_period(self) -> None:
        result = report(
            [
                summary("a", day="2026-10-19"),
                summary("b", 30, day="2026-10-21", sport="run"),
                summary("c", day="2026-10-26"),
                summary("outside", day="2026-10-27"),
            ],
            {key: {"session_rpe": 4} for key in ("a", "b", "c", "outside")},
            start="2026-10-19",
            end="2026-10-26",
        )
        self.assertEqual(len(result["days"]), 8)
        empty = next(day for day in result["days"] if day["date"] == "2026-10-20")
        self.assertEqual((empty["value"], empty["total_sessions"]), (None, 0))
        self.assertEqual(
            [
                (week["start"], week["value"], week["partial_period"])
                for week in result["weeks"]
            ],
            [("2026-10-19", 360.0, False), ("2026-10-26", 240.0, True)],
        )
        self.assertEqual(result["sports"]["run"]["value"], 120.0)
        self.assertEqual(result["sports"]["ride"]["value"], 480.0)
        self.assertEqual(
            [item["activity_id"] for item in result["sessions"]], ["c", "b", "a"]
        )

    def test_no_rated_session_gives_no_value(self) -> None:
        result = report([summary("a")], {})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["totals"]["value"])
        self.assertEqual(report([], {})["totals"]["total_sessions"], 0)

    def test_inputs_are_not_mutated(self) -> None:
        summaries = [summary("a", **provider_rpe(6))]
        feedback = {"a": {"session_rpe": 5, "session_rpe_rated_at": None}}
        before = copy.deepcopy((summaries, feedback))
        report(summaries, feedback)
        self.assertEqual((summaries, feedback), before)

    def test_training_report_carries_the_period_load(self) -> None:
        result = training_report(
            start=date.fromisoformat(DAY),
            days=7,
            today=date.fromisoformat(DAY),
            activity_summaries=[summary("a")],  # type: ignore[list-item]
            session_feedback={"a": {"session_rpe": 5}},
            computed_at="2026-10-21T10:00:00+02:00",
        )
        load = result["session_rpe_load"]
        self.assertEqual(load["totals"]["value"], 300.0)
        self.assertEqual(load["period"], {"start": DAY, "end": DAY, "timezone": "UTC"})
        self.assertEqual(load["computed_at"], "2026-10-21T10:00:00+02:00")
        self.assertEqual(result["totals"]["training_load"]["value"], None)


class SessionRpeLoadIntegrationTests(FeedbackSessionFixture):
    """Edits, undo and the two provider copies of one session, end to end."""

    undo = history.FeedbackHistoryTests.undo

    def load(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            summaries = activity_summaries(
                CanonicalTableReader().activity_sessions(db), ZONE
            )
        return session_rpe_load(
            summaries,
            feedback_by_session(summaries, self.service.for_activity_ids),
            start=date(2026, 9, 10),
            end=date(2026, 9, 10),
            timezone="Europe/Berlin",
        )

    def test_duplicate_provider_copies_count_once_with_the_intervals_fallback(
        self,
    ) -> None:
        result = self.load()
        self.assertEqual(result["totals"]["total_sessions"], 1)
        (session,) = result["sessions"]
        self.assertEqual(
            (session["value"], session["rpe"], session["rpe_source_label"]),
            (420.0, 7.0, "Intervals.icu"),
        )

    def test_edits_switch_the_source_and_undo_restores_the_previous_value(
        self,
    ) -> None:
        created = self.service.save(GARMIN_ID, {"session_rpe": 5})
        (session,) = self.load()["sessions"]
        self.assertEqual(
            (session["value"], session["rpe_source"]), (300.0, "athlete_feedback")
        )
        self.assertIsNotNone(session["rated_minutes_after_end"])
        edited = self.service.save(INTERVALS_ID, {"session_rpe": 6})
        self.assertEqual(self.load()["totals"]["value"], 360.0)
        self.undo(edited["change"])
        self.assertEqual(self.load()["totals"]["value"], 300.0)
        self.undo(created["change"])
        (session,) = self.load()["sessions"]
        self.assertEqual((session["value"], session["rpe_source"]), (420.0, "provider"))

    def test_clearing_the_local_rating_falls_back_to_the_provider_rating(
        self,
    ) -> None:
        self.service.save(INTERVALS_ID, {"session_rpe": 3, "notes": "kept"})
        self.assertEqual(self.load()["totals"]["value"], 180.0)
        self.service.save(INTERVALS_ID, {"session_rpe": None})
        (session,) = self.load()["sessions"]
        self.assertEqual((session["value"], session["rpe_source"]), (420.0, "provider"))


if __name__ == "__main__":
    unittest.main()
