"""Local fitness, fatigue and form (M7): reference values, warm-up, day states."""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta
from typing import Any

from support import flat, golden_history, golden_rows, golden_window
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


# Golden values captured from the implementation before the shared-walk refactor.
M7_TOTALS = {
    "metric_id": "local_fitness_fatigue",
    "method_id": "local-fitness-fatigue",
    "method_version": 1,
    "unit": "TSS/d",
    "status": "estimate",
    "reason": None,
    "period": {"start": "2026-01-01", "end": "2026-05-10", "timezone": "UTC"},
    "computed_at": "2026-05-10T08:00:00+00:00",
    "parameters": {
        "fitness_tau_days": 42,
        "fatigue_tau_days": 7,
        "warmup_days": {"fitness": 84, "fatigue": 14},
        "start_state": 0,
        "first_load_date": "2026-01-05",
        "load_method_id": "local-tss-load",
        "load_method_version": 7,
    },
    "coverage": {
        "loaded": 104,
        "incomplete": 3,
        "rest": 16,
        "open": 3,
        "no_history": 4,
    },
    "incomplete_days": 3,
    "incomplete_share": 0.023,
    "sessions_without_load": 3,
    "latest": (128, "loaded", 50.1, 49.0, 52.7, -3.7),
}
M7_DAYS = """
0,no_history,-,-,-,-; 1,no_history,-,-,-,-; 2,no_history,-,-,-,-;
3,no_history,-,-,-,-; 4,loaded,38.5,-,-,-; 5,loaded,50.0,-,-,-;
6,loaded,63.4,-,-,-; 7,loaded,76.7,-,-,-; 8,loaded,40.1,-,-,-;
9,loaded,53.5,-,-,-; 10,rest,0.0,-,-,-; 11,loaded,78.4,-,-,-;
12,loaded,41.7,-,-,-; 13,loaded,55.1,-,-,-; 14,loaded,68.5,-,-,-;
15,loaded,80.0,-,-,-; 16,loaded,43.4,-,-,-; 17,rest,0.0,-,-,-;
18,loaded,70.1,-,44.2,-; 19,loaded,83.5,-,49.4,-;
20,incomplete,45.0,-,48.8,-,1,270.0; 21,loaded,58.4,-,50.1,-;
22,loaded,71.7,-,53.0,-; 23,loaded,85.1,-,57.2,-; 24,rest,0.0,-,49.6,-;
25,loaded,60.0,-,51.0,-; 26,loaded,73.4,-,54.0,-; 27,loaded,36.7,-,51.7,-;
28,loaded,50.1,-,51.5,-; 29,loaded,63.5,-,53.1,-; 30,loaded,75.0,-,56.0,-;
31,rest,0.0,-,48.5,-; 32,loaded,51.7,-,49.0,-; 33,loaded,65.1,-,51.1,-;
34,loaded,78.5,-,54.8,-; 35,loaded,40.0,-,52.8,-; 36,loaded,53.4,-,52.9,-;
37,loaded,66.7,-,54.7,-; 38,rest,0.0,-,47.4,-; 39,loaded,43.5,-,46.9,-;
40,loaded,55.0,-,48.0,-; 41,loaded,68.4,-,50.7,-; 42,loaded,81.7,-,54.8,-;
43,loaded,45.1,-,53.5,-; 44,loaded,58.5,-,54.2,-; 45,rest,0.0,-,47.0,-;
46,loaded,83.4,-,51.8,-; 47,loaded,46.7,-,51.1,-; 48,loaded,60.1,-,52.3,-;
49,loaded,73.5,-,55.2,-; 50,loaded,35.0,-,52.5,-; 51,loaded,48.4,-,51.9,-;
52,incomplete,0.0,-,45.0,-,1,315.0; 53,loaded,75.1,-,49.0,-;
54,loaded,38.5,-,47.6,-; 55,loaded,50.0,-,47.9,-; 56,loaded,63.4,-,50.0,-;
57,loaded,76.7,-,53.5,-; 58,loaded,40.1,-,51.8,-; 59,rest,0.0,-,44.9,-;
60,loaded,65.0,-,47.6,-; 61,loaded,78.4,-,51.7,-; 62,loaded,41.7,-,50.3,-;
63,loaded,55.1,-,51.0,-; 64,loaded,68.5,-,53.3,-; 65,loaded,80.0,-,56.9,-;
66,rest,0.0,-,49.3,-; 67,loaded,56.7,-,50.3,-; 68,loaded,70.1,-,52.9,-;
69,loaded,83.5,-,57.0,-; 70,loaded,45.0,-,55.4,-; 71,loaded,58.4,-,55.8,-;
72,loaded,71.7,-,57.9,-; 73,rest,0.0,-,50.2,-; 74,loaded,48.5,-,50.0,-;
75,loaded,60.0,-,51.3,-; 76,loaded,73.4,-,54.2,-; 77,loaded,36.7,-,51.9,-;
78,loaded,50.1,-,51.7,-; 79,loaded,63.5,-,53.2,-; 80,rest,0.0,-,46.2,-;
81,loaded,38.4,-,45.1,-; 82,loaded,51.7,-,46.0,-; 83,loaded,65.1,-,48.5,-;
84,loaded,78.5,-,52.5,-; 85,loaded,40.0,-,50.9,-; 86,loaded,53.4,-,51.2,-;
87,rest,0.0,-,44.4,-; 88,loaded,80.1,44.1,49.1,-5.0;
89,loaded,43.5,44.1,48.4,-4.3; 90,incomplete,55.0,44.4,49.3,-4.9,1,-;
91,loaded,68.4,44.9,51.8,-6.9; 92,loaded,81.7,45.8,55.8,-10.0;
93,loaded,45.1,45.8,54.4,-8.6; 94,rest,0.0,44.7,47.1,-2.4;
95,loaded,70.0,45.3,50.2,-4.9; 96,loaded,83.4,46.2,54.6,-8.4;
97,loaded,46.7,46.2,53.5,-7.4; 98,loaded,60.1,46.5,54.4,-7.9;
99,loaded,73.5,47.2,57.0,-9.8; 100,loaded,35.0,46.9,54.0,-7.2;
101,rest,0.0,45.8,46.8,-1.1; 102,loaded,61.7,46.1,48.8,-2.7;
103,loaded,75.1,46.8,52.3,-5.5; 104,loaded,38.5,46.6,50.5,-3.9;
105,loaded,50.0,46.7,50.4,-3.7; 106,loaded,63.4,47.1,52.1,-5.0;
107,loaded,76.7,47.8,55.4,-7.6; 108,rest,0.0,46.7,48.0,-1.4;
109,loaded,53.5,46.8,48.8,-1.9; 110,loaded,65.0,47.3,50.9,-3.7;
111,loaded,78.4,48.0,54.6,-6.6; 112,loaded,41.7,47.8,52.9,-5.0;
113,loaded,55.1,48.0,53.2,-5.2; 114,loaded,68.5,48.5,55.2,-6.7;
115,rest,0.0,47.4,47.9,-0.5; 116,loaded,43.4,47.3,47.3,0.0;
117,loaded,56.7,47.5,48.5,-1.0; 118,loaded,70.1,48.0,51.4,-3.4;
119,loaded,83.5,48.9,55.7,-6.8; 120,loaded,45.0,48.8,54.2,-5.5;
121,loaded,58.4,49.0,54.8,-5.8; 122,rest,0.0,47.8,47.5,0.3;
123,loaded,85.1,48.7,52.5,-3.8; 124,loaded,48.5,48.7,52.0,-3.3;
125,loaded,60.0,49.0,53.0,-4.1; 126,open,-,-,-,-; 127,open,-,-,-,-;
128,loaded,50.1,49.0,52.7,-3.7; 129,open,-,-,-,-
"""


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
        self.assertEqual(marked["incomplete_days"], 1)
        self.assertEqual(marked["incomplete_share"], 0.01)
        self.assertEqual((plain["incomplete_days"], plain["incomplete_share"]), (0, 0))

    def test_day_with_only_unloaded_sessions_counts_zero(self) -> None:
        loads = {day(0): 100.0}
        result = run(loads, 20, [summary("yoga", 30, day(20), sport="yoga")])
        last = result["days"][-1]
        self.assertEqual((last["state"], last["load"]), ("incomplete", 0.0))
        self.assertIsNone(last["session_rpe_au_without_load"])

    def test_sessions_before_the_first_load_day_are_marked(self) -> None:
        result = run({day(5): 80.0}, 6, [summary("gym", 40, day(2), sport="strength")])
        row = result["days"][2]
        self.assertEqual(
            (row["state"], row["sessions_without_load"]), ("no_history", 1)
        )
        self.assertEqual(result["sessions_without_load"], 1)

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

    def test_golden_history_pins_every_field_of_every_day(self) -> None:
        sessions, feedback, loads = golden_history()
        result = local_fitness_fatigue(loads, sessions, feedback, **golden_window(0))
        days = [flat(day) for day in result.pop("days")]
        for text in ("method", "limits", "evidence_card"):
            del result[text]
        result["latest"] = flat(result["latest"])
        self.assertEqual(result, M7_TOTALS)
        self.assertEqual(days, golden_rows(M7_DAYS))


if __name__ == "__main__":
    unittest.main()
