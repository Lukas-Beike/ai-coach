"""Smoothed session-RPE load (M5): reference values, gaps, warm-up, no seeding."""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta
from typing import Any

from support import GOLDEN_FIRST as FIRST
from support import flat, golden_history, golden_rows, golden_window
from test_session_rpe_load import summary

from backend.performance.smoothed_load import (
    LONG_TAU_DAYS,
    SHORT_TAU_DAYS,
    complete_before,
    history_start,
    smoothed_session_load,
)


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


# Golden values captured from the implementation before the shared-walk refactor.
M5_TOTALS = {
    "metric_id": "smoothed_session_load",
    "method_id": "smoothed-session-load",
    "method_version": 1,
    "unit": "AU",
    "status": "estimate",
    "reason": None,
    "period": {"start": "2026-01-01", "end": "2026-05-10", "timezone": "UTC"},
    "computed_at": "2026-05-10T08:00:00+00:00",
    "parameters": {
        "short_tau_days": 7,
        "long_tau_days": 42,
        "warmup_days": {"short": 14, "long": 84},
        "start_state_au": 0,
        "first_session_date": "2026-01-05",
    },
    "coverage": {"rated": 103, "rest": 16, "gap": 4, "open": 3, "no_history": 4},
    "latest": (128, "rated", 217.0, 289.3, 301.9),
}
M5_DAYS = """
0,no_history,-,-,-; 1,no_history,-,-,-; 2,no_history,-,-,-; 3,no_history,-,-,-;
4,rated,490.0,-,-; 5,rated,160.0,-,-; 6,rated,171.0,-,-; 7,rated,592.0,-,-;
8,rated,637.0,-,-; 9,rated,198.0,-,-; 10,rest,0.0,-,-; 11,rated,268.0,-,-;
12,rated,252.0,-,-; 13,rated,808.0,-,-; 14,rated,301.0,-,-; 15,rated,360.0,-,-;
16,rated,385.0,-,-; 17,rest,0.0,-,-; 18,rated,108.0,247.0,-;
19,rated,424.0,270.6,-; 20,rated,760.0,335.7,-; 21,rated,522.0,360.5,-;
22,rated,520.0,381.7,-; 23,rated,184.0,355.4,-; 24,rest,0.0,308.1,-;
25,rated,640.0,352.3,-; 26,rated,679.0,395.8,-; 27,rated,234.0,374.2,-;
28,rated,280.0,361.7,-; 29,rated,292.0,352.4,-; 30,rated,270.0,341.4,-;
31,rest,0.0,296.0,-; 32,rated,343.0,302.3,-; 33,rated,396.0,314.7,-;
34,rated,415.0,328.1,-; 35,rated,400.0,337.7,-; 36,rated,126.0,309.5,-;
37,rated,472.0,331.1,-; 38,rest,0.0,287.0,-; 39,rated,558.0,323.1,-;
40,gap,-,-,-; 41,gap,-,-,-; 42,rated,207.0,307.6,-; 43,rated,688.0,358.3,-;
44,rated,721.0,406.6,-; 45,rest,0.0,352.4,-; 46,rated,310.0,346.8,-;
47,rated,316.0,342.7,-; 48,rated,288.0,335.4,-; 49,rated,304.0,331.2,-;
50,rated,385.0,338.4,-; 51,rated,432.0,350.9,-; 52,rated,315.0,346.1,-;
53,rated,124.0,316.5,-; 54,rated,144.0,293.5,-; 55,rated,520.0,323.7,-;
56,rated,574.0,357.0,-; 57,rated,594.0,388.6,-; 58,rated,205.0,364.1,-;
59,rest,0.0,315.7,-; 60,rated,225.0,303.6,-; 61,rated,736.0,361.1,-;
62,rated,238.0,344.8,-; 63,rated,306.0,339.6,-; 64,rated,340.0,339.7,-;
65,rated,340.0,339.7,-; 66,rest,0.0,294.5,-; 67,rated,352.0,302.1,-;
68,rated,427.0,318.8,-; 69,rated,468.0,338.6,-; 70,rated,475.0,356.8,-;
71,rated,148.0,329.0,-; 72,rated,162.0,306.8,-; 73,rest,0.0,265.9,-;
74,rated,616.0,312.5,-; 75,rated,180.0,294.9,-; 76,rated,235.0,286.9,-;
77,rated,256.0,282.8,-; 78,rated,243.0,277.5,-; 79,rated,784.0,344.9,-;
80,rest,0.0,299.0,-; 81,rated,342.0,304.7,-; 82,rated,370.0,313.4,-;
83,rated,364.0,320.2,-; 84,rated,99.0,290.7,-; 85,rated,400.0,305.3,-;
86,rated,469.0,327.1,-; 87,rest,0.0,283.5,-; 88,rated,505.0,313.0,277.5;
89,rated,172.0,294.2,275.0; 90,gap,-,-,-; 91,rated,616.0,337.1,283.0;
92,rated,658.0,379.8,291.9; 93,rated,216.0,358.0,290.1; 94,rest,0.0,310.3,283.3;
95,gap,-,-,-; 96,rated,261.0,303.8,282.7; 97,rated,832.0,374.1,295.7;
98,rated,322.0,367.1,296.3; 99,rated,378.0,368.6,298.2;
100,rated,400.0,372.8,300.6; 101,rest,0.0,323.2,293.5;
102,rated,117.0,295.7,289.4; 103,rated,448.0,316.0,293.1;
104,rated,511.0,341.9,298.2; 105,rated,540.0,368.3,303.9;
106,rated,160.0,340.6,300.5; 107,rated,196.0,321.3,298.1;
108,rest,0.0,278.6,291.1; 109,rated,664.0,329.9,299.8;
110,rated,700.0,379.1,309.2; 111,rated,252.0,362.2,307.9;
112,rated,295.0,353.3,307.6; 113,rated,304.0,346.7,307.5;
114,rated,279.0,337.7,306.8; 115,rest,0.0,292.7,299.6;
116,rated,364.0,302.2,301.1; 117,rated,414.0,317.1,303.8;
118,rated,430.0,332.1,306.8; 119,rated,412.0,342.8,309.2;
120,rated,135.0,315.1,305.1; 121,rated,496.0,339.2,309.6;
122,rest,0.0,294.0,302.3; 123,rated,576.0,331.6,308.8;
124,rated,190.0,312.7,306.0; 125,rated,220.0,300.4,304.0; 126,open,-,-,-;
127,open,-,-,-; 128,rated,217.0,289.3,301.9; 129,open,-,-,-
"""


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

    def test_golden_history_pins_every_field_of_every_day(self) -> None:
        sessions, feedback, _ = golden_history()
        result = smoothed_session_load(sessions, feedback, **golden_window(0))
        days = [flat(day) for day in result.pop("days")]
        for text in ("method", "limits", "evidence_card"):
            del result[text]
        result["latest"] = flat(result["latest"])
        self.assertEqual(result, M5_TOTALS)
        self.assertEqual(days, golden_rows(M5_DAYS))


if __name__ == "__main__":
    unittest.main()
