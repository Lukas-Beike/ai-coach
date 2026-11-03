"""Smoothed session-RPE load (M5): reference values, gaps, warm-up, no seeding."""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta
from typing import Any

from test_session_rpe_load import summary

from backend.performance.smoothed_load import (
    LONG_TAU_DAYS,
    SHORT_TAU_DAYS,
    complete_before,
    history_start,
    smoothed_session_load,
)

FIRST = date(2026, 1, 1)


def session(offset: int, minutes: float = 60) -> dict[str, Any]:
    day = (FIRST + timedelta(days=offset)).isoformat()
    return summary(f"s{offset}", minutes, day)


def rated(*offsets: int, rpe: float = 5) -> dict[str, dict[str, Any]]:
    return {f"s{offset}": {"session_rpe": rpe} for offset in offsets}


def run(sessions, feedback, end_offset: int, **kw) -> dict[str, Any]:
    end = FIRST + timedelta(days=end_offset)
    return smoothed_session_load(
        sessions,
        feedback,
        start=kw.pop("start", FIRST),
        end=end,
        today=kw.pop("today", end + timedelta(days=30)),
        timezone="UTC",
        **kw,
    )


def reference(loads: list[float], tau: int) -> float:
    state, decay = 0.0, math.exp(-1 / tau)
    for load in loads:
        state = decay * state + (1 - decay) * load
    return state


class SmoothedLoadTests(unittest.TestCase):
    def test_recursion_matches_reference_after_warmup(self) -> None:
        sessions = [session(offset) for offset in range(0, 100, 2)]
        result = run(sessions, rated(*range(0, 100, 2)), 99)
        loads = [300.0 if offset % 2 == 0 else 0.0 for offset in range(100)]
        last = result["days"][-1]
        self.assertEqual(last["short"], round(reference(loads, SHORT_TAU_DAYS), 1))
        self.assertEqual(last["long"], round(reference(loads, LONG_TAU_DAYS), 1))
        self.assertEqual(result["status"], "estimate")
        self.assertEqual(result["parameters"]["start_state_au"], 0)

    def test_warmup_withholds_values_per_curve(self) -> None:
        result = run([session(0)], rated(0), 20)
        days = result["days"]
        self.assertIsNone(days[13]["short"])
        self.assertIsNotNone(days[14]["short"])
        self.assertTrue(all(day["long"] is None for day in days))

    def test_only_warmup_is_insufficient_data(self) -> None:
        result = run([session(0)], rated(0), 5)
        self.assertEqual(
            (result["status"], result["reason"]), ("insufficient_data", "warmup")
        )
        self.assertIsNone(result["latest"])

    def test_no_sessions(self) -> None:
        result = run([], {}, 10)
        self.assertEqual(
            (result["status"], result["reason"]), ("insufficient_data", "no_sessions")
        )
        self.assertEqual({day["state"] for day in result["days"]}, {"no_history"})

    def test_unrated_session_is_a_gap_not_zero(self) -> None:
        sessions = [session(0), session(20), session(21)]
        gap = run(sessions, rated(0, 21), 21)
        self.assertEqual(gap["days"][20]["state"], "gap")
        self.assertIsNone(gap["days"][20]["short"])
        self.assertEqual(gap["coverage"]["gap"], 1)
        zero = run(sessions, {**rated(0, 21), "s20": {"session_rpe": 0}}, 21)
        self.assertNotEqual(gap["days"][21]["short"], zero["days"][21]["short"])
        held = reference([300.0] + [0.0] * 19, SHORT_TAU_DAYS)
        decay = math.exp(-1 / SHORT_TAU_DAYS)
        self.assertEqual(
            gap["days"][21]["short"],
            round(decay * held + (1 - decay) * 300.0, 1),
        )

    def test_day_with_one_unrated_session_is_a_gap(self) -> None:
        sessions = [session(0), {**session(0), "id": "extra"}]
        result = run(sessions, rated(0), 0)
        self.assertEqual(result["days"][0]["state"], "gap")

    def test_open_today_without_session_has_no_value(self) -> None:
        sessions = [session(0)]
        result = run(sessions, rated(0), 20, today=FIRST + timedelta(days=20))
        self.assertEqual(result["days"][-1]["state"], "open")
        self.assertIsNone(result["days"][-1]["short"])

    def test_provider_load_does_not_seed_the_curve(self) -> None:
        sessions = [session(0)]
        poisoned = [{**sessions[0], "load": 900, "training_load": 900, "ctl": 80}]
        self.assertEqual(
            run(sessions, rated(0), 30)["days"],
            run(poisoned, rated(0), 30)["days"],
        )

    def test_history_before_start_feeds_the_period(self) -> None:
        sessions = [session(offset) for offset in range(150)]
        result = run(
            sessions, rated(*range(150)), 149, start=FIRST + timedelta(days=100)
        )
        self.assertIsNotNone(result["days"][0]["long"])
        self.assertEqual(len(result["days"]), 50)

    def test_days_after_the_last_sync_are_open_not_rest(self) -> None:
        sessions: Any = [session(0)]
        end = FIRST + timedelta(days=20)
        result = smoothed_session_load(
            sessions,
            rated(0),
            start=FIRST,
            end=end,
            today=end,
            complete_before=FIRST + timedelta(days=17),
            timezone="UTC",
        )
        self.assertEqual(
            [day["state"] for day in result["days"][-5:]],
            ["rest", "open", "open", "open", "open"],
        )
        self.assertEqual(result["days"][-1]["short"], None)

    def test_sync_time_gives_the_first_incomplete_day(self) -> None:
        today = date(2026, 3, 10)
        self.assertEqual(
            complete_before(today, "2026-03-07T23:30:00+00:00", "Europe/Berlin"),
            date(2026, 3, 8),
        )
        self.assertEqual(complete_before(today, None, "UTC"), today)
        self.assertEqual(complete_before(today, "bad", "UTC"), today)

    def test_established_athlete_has_values_from_the_first_day(self) -> None:
        today = FIRST + timedelta(days=400)
        start = today - timedelta(days=83)
        origin = history_start(start, today)
        offsets = range((origin - FIRST).days + 3, 401)
        sessions: Any = [session(o) for o in offsets]
        result = smoothed_session_load(
            sessions,
            rated(*offsets),
            start=start,
            end=today,
            today=today,
            timezone="UTC",
        )
        self.assertIsNotNone(result["days"][0]["long"])
        self.assertEqual(history_start(today - timedelta(days=6), today), origin)


if __name__ == "__main__":
    unittest.main()
