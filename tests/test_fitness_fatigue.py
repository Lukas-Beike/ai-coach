"""Local fitness, fatigue and form (M7): reference values, warm-up, day states."""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta
from typing import Any

from test_session_rpe_load import summary

from backend.performance.fitness_fatigue import (
    FATIGUE_TAU_DAYS,
    FITNESS_TAU_DAYS,
    local_fitness_fatigue,
)

FIRST = date(2026, 1, 1)


def day(offset: int) -> str:
    return (FIRST + timedelta(days=offset)).isoformat()


def run(loads, end_offset: int, summaries=(), feedback=None, **kw) -> dict[str, Any]:
    end = FIRST + timedelta(days=end_offset)
    return local_fitness_fatigue(
        loads,
        list(summaries),
        feedback or {},
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


class LocalFitnessFatigueTests(unittest.TestCase):
    def test_recursion_and_form_match_reference_after_warmup(self) -> None:
        loads = {day(offset): 80.0 for offset in range(0, 120, 2)}
        result = run(loads, 119)
        daily = [80.0 if offset % 2 == 0 else 0.0 for offset in range(120)]
        fitness = reference(daily, FITNESS_TAU_DAYS)
        fatigue = reference(daily, FATIGUE_TAU_DAYS)
        last = result["days"][-1]
        self.assertEqual(last["fitness"], round(fitness, 1))
        self.assertEqual(last["fatigue"], round(fatigue, 1))
        self.assertEqual(last["form"], round(fitness - fatigue, 1))
        self.assertEqual(last["state"], "rest")
        self.assertEqual(result["status"], "estimate")
        self.assertEqual(result["unit"], "TSS/d")
        self.assertEqual(result["parameters"]["first_load_date"], day(0))

    def test_warmup_withholds_each_curve_and_form(self) -> None:
        result = run({day(0): 100.0}, 90)
        days = result["days"]
        self.assertIsNone(days[13]["fatigue"])
        self.assertIsNotNone(days[14]["fatigue"])
        self.assertIsNone(days[83]["fitness"])
        self.assertIsNone(days[83]["form"])
        self.assertIsNotNone(days[84]["fitness"])
        self.assertIsNotNone(days[84]["form"])

    def test_history_before_the_period_seeds_the_curve(self) -> None:
        loads = {day(offset): 60.0 for offset in range(200)}
        full = run(loads, 199)
        window = run(loads, 199, start=FIRST + timedelta(days=190))
        self.assertEqual(window["days"], full["days"][190:])
        self.assertEqual(window["days"][0]["state"], "loaded")

    def test_no_load(self) -> None:
        result = run({}, 10)
        self.assertEqual(
            (result["status"], result["reason"]), ("insufficient_data", "no_load")
        )
        self.assertEqual(result["coverage"]["no_history"], 11)

    def test_session_without_load_adds_nothing_and_marks_the_day(self) -> None:
        loads = {day(offset): 50.0 for offset in range(100)}
        strength = summary("strength", 45, day(95), sport="strength")
        rated = {"strength": {"session_rpe": 6}}
        marked = run(loads, 99, [strength], rated)
        plain = run(loads, 99)
        self.assertEqual(
            [row["fitness"] for row in marked["days"]],
            [row["fitness"] for row in plain["days"]],
        )
        row = marked["days"][95]
        self.assertEqual(row["state"], "incomplete")
        self.assertEqual(row["sessions_without_load"], 1)
        self.assertEqual(row["session_rpe_au_without_load"], 270.0)
        self.assertEqual(marked["sessions_without_load"], 1)

    def test_day_with_only_unloaded_sessions_counts_zero(self) -> None:
        loads = {day(0): 100.0}
        result = run(loads, 20, [summary("yoga", 30, day(20), sport="yoga")])
        last = result["days"][-1]
        self.assertEqual((last["state"], last["load"]), ("incomplete", 0.0))
        self.assertIsNone(last["session_rpe_au_without_load"])

    def test_loaded_sessions_are_not_marked(self) -> None:
        loads = {day(0): 100.0}
        ride = summary("ride", 60, day(0), training_load=100.0)
        result = run(loads, 0, [ride])
        self.assertEqual(result["days"][0]["state"], "loaded")
        self.assertNotIn("sessions_without_load", result["days"][0])

    def test_open_days_have_no_value_and_hold_the_state(self) -> None:
        loads = {day(offset): 70.0 for offset in range(30)}
        end = FIRST + timedelta(days=31)
        result = run(loads, 31, today=end, complete_before=end - timedelta(days=1))
        open_day = result["days"][30]
        self.assertEqual((open_day["state"], open_day["fatigue"]), ("open", None))
        self.assertEqual(result["latest"]["date"], day(29))
        self.assertEqual(result["coverage"]["open"], 2)

    def test_rest_day_decays(self) -> None:
        result = run({day(offset): 90.0 for offset in range(20)}, 21)
        rest = result["days"][20]
        self.assertEqual(rest["state"], "rest")
        self.assertLess(rest["fatigue"], result["days"][19]["fatigue"])

    def test_loads_after_the_period_are_ignored(self) -> None:
        loads = {day(offset): 40.0 for offset in range(30)}
        self.assertEqual(
            run(loads, 20)["days"],
            run({key: value for key, value in loads.items() if key <= day(20)}, 20)[
                "days"
            ],
        )


if __name__ == "__main__":
    unittest.main()
