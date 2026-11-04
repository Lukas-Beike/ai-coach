"""One session's execution against comparable earlier sessions."""

from __future__ import annotations

import unittest
from typing import Any

from session_stream_support import synthetic_session

from backend.performance.comparable_sessions import comparable_sessions
from backend.performance.session_execution import (
    comparison_metrics,
    session_execution,
)


def _easy(
    output: int, heart: int, drift: int = 3, seconds: int = 3000
) -> dict[str, Any]:
    return {
        "structure": "continuous",
        "output_unit": "s/km",
        "main_part_s": seconds,
        "output": output,
        "heart_rate_avg": heart,
        "heart_rate_change_bpm": drift,
        "cadence": 170,
    }


def _row(day: str, summary: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    return {
        "activity_id": f"act_{day}",
        "date": day,
        "sport": fields.get("sport", "run"),
        "environment": fields.get("environment", "outdoor"),
        "name": "Easy",
        "avg_temp_c": fields.get("temp", 12.0),
        "execution_summary": summary,
    }


class ComparableSessionsTests(unittest.TestCase):
    def test_easy_runs_compare_with_the_median_of_their_peers(self) -> None:
        records = [
            _row("2026-11-03", _easy(330, 140, drift=2), temp=8.0),
            _row("2026-10-27", _easy(340, 145)),
            _row("2026-10-20", _easy(345, 146)),
            _row("2026-10-13", _easy(350, 148)),
            _row("2026-10-06", _easy(352, 150), temp=24.0),
        ]
        result = comparable_sessions(records, "act_2026-11-03")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["median_of_peers"]["output"], 348)
        self.assertEqual(result["difference"]["output"], -18)
        self.assertEqual(result["difference"]["heart_rate_avg"], -7)
        self.assertEqual(result["this"]["avg_temp_c"], 8.0)
        self.assertEqual(result["peers"][0]["date"], "2026-10-27")

    def test_other_shapes_places_and_old_sessions_are_not_peers(self) -> None:
        records = [
            _row("2026-11-03", _easy(330, 140)),
            _row("2026-10-30", _easy(340, 145), environment="indoor"),
            _row("2026-10-29", _easy(340, 145), sport="ride"),
            _row("2026-10-28", _easy(340, 145, seconds=6000)),
            _row("2026-07-01", _easy(340, 145)),
            _row("2026-10-27", _easy(340, 145)),
            _row("2026-11-05", _easy(340, 145)),
        ]
        result = comparable_sessions(records, "act_2026-11-03")
        self.assertEqual(result["status"], "not_covered")
        self.assertEqual(result["count"], 1)

    def test_interval_sessions_need_similar_reps(self) -> None:
        def reps(count: int, seconds: int, output: int) -> dict[str, Any]:
            return {
                "structure": "interval",
                "output_unit": "s/km",
                "rep_count": count,
                "median_rep_s": seconds,
                "rep_output_mean": output,
                "heart_rate_end_mean": 170,
                "recovery_drop_mean": 25,
                "first_to_last_change_pct": -2.0,
            }

        records = [
            _row("2026-11-03", reps(5, 180, 240)),
            _row("2026-10-27", reps(6, 180, 245)),
            _row("2026-10-20", reps(5, 200, 248)),
            _row("2026-10-13", reps(4, 170, 250)),
            _row("2026-10-06", reps(10, 60, 220)),
        ]
        result = comparable_sessions(records, "act_2026-11-03")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["difference"]["rep_output_mean"], -8)

    def test_a_session_without_execution_is_not_covered(self) -> None:
        result = comparable_sessions([_row("2026-11-03", None)], "act_2026-11-03")
        self.assertEqual(result["status"], "not_covered")


class ComparisonMetricsTests(unittest.TestCase):
    def test_continuous_and_interval_summaries(self) -> None:
        easy = session_execution(
            synthetic_session([("lap", 3600, 3.0, (135.0, 150.0))], kinds=False)
        )
        metrics = comparison_metrics(easy)
        self.assertEqual(metrics["structure"], "continuous")
        self.assertEqual(metrics["output"], 333)
        self.assertEqual(metrics["main_part_s"], 3000)
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0))
        ]
        for _ in range(4):
            segments += [
                ("work", 180, 4.5, (150.0, 170.0)),
                ("recovery", 90, 2.5, (170.0, 140.0)),
            ]
        intervals = comparison_metrics(session_execution(synthetic_session(segments)))
        self.assertEqual(intervals["rep_count"], 4)
        self.assertEqual(intervals["median_rep_s"], 180)
        self.assertEqual(intervals["rep_output_mean"], 222)
        self.assertEqual(intervals["heart_rate_end_mean"], 169)
        self.assertIsNone(comparison_metrics({"status": "insufficient_data"}))


if __name__ == "__main__":
    unittest.main()
