"""Lap-by-lap execution of one run or ride from synthetic streams."""

from __future__ import annotations

import unittest
from typing import Any

from backend.performance.session_execution import session_execution


def _session(
    segments: list[tuple[str, int, float, tuple[float, float]]],
    *,
    sport: str = "run",
    output: str = "velocity_smooth",
    cadence: float | None = 85.0,
    kinds: bool = True,
) -> dict[str, Any]:
    """1 Hz streams from (kind, seconds, output, (start hr, end hr)) segments."""
    times: list[int] = []
    values: list[float] = []
    heart: list[float] = []
    laps: list[dict[str, Any]] = []
    clock = 0
    for kind, seconds, value, (hr_start, hr_end) in segments:
        laps.append(
            {
                "start_time": float(clock),
                "end_time": float(clock + seconds),
                "kind": kind if kinds else "lap",
                "distance_m": None,
            }
        )
        for second in range(seconds):
            times.append(clock + second)
            values.append(value)
            heart.append(hr_start + (hr_end - hr_start) * second / max(1, seconds - 1))
        clock += seconds
    times.append(clock)
    values.append(values[-1])
    heart.append(heart[-1])
    streams: dict[str, Any] = {
        "time": times,
        output: values,
        "heartrate": heart,
        "moving": [True] * len(times),
    }
    if cadence is not None:
        streams["cadence"] = [cadence] * len(times)
    return {"sport": sport, "streams": streams, "laps": laps}


def _interval_run(kinds: bool = True, last_speed: float = 4.2) -> dict[str, Any]:
    segments: list[tuple[str, int, float, tuple[float, float]]] = [
        ("warmup", 600, 3.0, (120.0, 135.0))
    ]
    for rep in range(5):
        speed = last_speed if rep == 4 else 4.5
        segments.append(("work", 180, speed, (150.0, 170.0 + rep)))
        if rep < 4:
            segments.append(("recovery", 90, 2.5, (170.0 + rep, 140.0 + rep * 2)))
    segments.append(("cooldown", 300, 2.8, (140.0, 125.0)))
    return _session(segments, kinds=kinds)


class SessionExecutionTests(unittest.TestCase):
    def test_labelled_intervals_give_reps_recoveries_and_summary(self) -> None:
        result = session_execution(_interval_run(), source_label="Garmin Connect")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structure"], "interval")
        self.assertEqual(result["structure_origin"], "lap_kinds")
        self.assertEqual((result["output"], result["output_unit"]), ("pace", "s/km"))
        reps = result["reps"]
        self.assertEqual(len(reps), 5)
        self.assertEqual(reps[0]["output"], 222)
        self.assertEqual(reps[4]["output"], 238)
        self.assertFalse(reps[0]["short"])
        self.assertEqual(reps[0]["within_rep_change_pct"], 0.0)
        self.assertEqual(reps[0]["cadence"], 170)
        self.assertGreaterEqual(reps[0]["heart_rate_end"], 169)
        summary = result["rep_summary"]
        self.assertEqual(summary["rep_count"], 5)
        self.assertEqual(summary["first_to_last_change_pct"], -6.7)
        self.assertEqual(len(result["recoveries"]), 4)
        recovery = result["recoveries"][0]
        self.assertEqual(recovery["after_rep"], 1)
        self.assertEqual(recovery["duration_s"], 90)
        self.assertGreater(recovery["heart_rate_drop_60s"], 15)
        self.assertIn("recovery_drop_last", summary)
        self.assertEqual(result["warmup"]["duration_s"], 600)
        self.assertEqual(result["cooldown"]["duration_s"], 300)
        self.assertEqual(result["source"], "Garmin Connect")

    def test_unlabelled_laps_are_split_by_output(self) -> None:
        result = session_execution(_interval_run(kinds=False))
        self.assertEqual(result["structure"], "interval")
        self.assertEqual(result["structure_origin"], "lap_output")
        self.assertEqual(len(result["reps"]), 5)
        self.assertEqual(result["warmup"]["duration_s"], 600)
        self.assertEqual(result["cooldown"]["duration_s"], 300)

    def test_equal_auto_laps_stay_one_continuous_run(self) -> None:
        segments = [("lap", 330, 3.0, (140.0, 150.0)) for _ in range(10)]
        result = session_execution(_session(segments, kinds=False))
        self.assertEqual(result["structure"], "continuous")
        halves = result["halves"]
        self.assertEqual(halves["status"], "ok")
        self.assertEqual(halves["first"]["output"], 333)
        self.assertEqual(halves["change_pct"], 0.0)
        self.assertEqual(halves["cadence_change"], 0)

    def test_easy_run_reports_heart_rate_drift_in_the_main_part(self) -> None:
        result = session_execution(
            _session([("lap", 3600, 3.0, (135.0, 155.0))], kinds=False)
        )
        halves = result["halves"]
        # The first 10 minutes are warm-up and stay out of the halves.
        self.assertEqual(halves["main_part_s"], 3000)
        self.assertGreaterEqual(halves["heart_rate_change_bpm"], 7)

    def test_short_reps_are_flagged(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0))
        ]
        for _ in range(6):
            segments += [
                ("work", 60, 5.0, (150.0, 165.0)),
                ("recovery", 60, 2.5, (165.0, 150.0)),
            ]
        result = session_execution(_session(segments))
        self.assertTrue(all(rep["short"] for rep in result["reps"]))
        self.assertNotIn("heart_rate_end_first", result["rep_summary"])
        # A 60 s recovery is too short for the 60 s drop.
        self.assertNotIn("heart_rate_drop_60s", result["recoveries"][0])

    def test_rides_report_power(self) -> None:
        segments = [
            ("warmup", 600, 150.0, (110.0, 125.0)),
            ("work", 480, 280.0, (150.0, 165.0)),
            ("recovery", 240, 120.0, (165.0, 130.0)),
            ("work", 480, 270.0, (150.0, 168.0)),
            ("cooldown", 300, 130.0, (130.0, 115.0)),
        ]
        result = session_execution(
            _session(segments, sport="ride", output="watts", cadence=90.0)
        )
        self.assertEqual((result["output"], result["output_unit"]), ("power", "W"))
        self.assertEqual([rep["output"] for rep in result["reps"]], [280, 270])
        self.assertEqual(result["reps"][0]["cadence"], 90)

    def test_data_quality_flags(self) -> None:
        clean = session_execution(_session([("lap", 1800, 3.0, (140.0, 145.0))]))
        self.assertEqual(clean["data_quality"], {"heart_rate": "ok", "speed": "ok"})
        spiky = _session([("lap", 1800, 3.0, (140.0, 145.0))])
        heart = spiky["streams"]["heartrate"]
        for index in range(0, len(heart), 20):
            heart[index] = 200.0
        speed = spiky["streams"]["velocity_smooth"]
        for index in range(0, len(speed), 30):
            speed[index] = 9.0
        flagged = session_execution(spiky)["data_quality"]
        self.assertEqual(flagged, {"heart_rate": "spikes", "speed": "jumps"})
        # Heart rate following a changing step cadence is locked onto it.
        locked = _session([("lap", 1800, 3.0, (170.0, 170.0))], cadence=85.0)
        steps = [
            80.0 + (index // 60) % 10 for index in range(len(locked["streams"]["time"]))
        ]
        locked["streams"]["cadence"] = steps
        locked["streams"]["heartrate"] = [step * 2 for step in steps]
        self.assertEqual(
            session_execution(locked)["data_quality"]["heart_rate"],
            "possible_cadence_lock",
        )
        # A tempo run whose heart rate merely equals its steady cadence is fine.
        tempo = _session([("lap", 1800, 3.5, (170.0, 170.0))], cadence=85.0)
        self.assertEqual(session_execution(tempo)["data_quality"]["heart_rate"], "ok")

    def test_steady_laps_with_one_slow_lap_stay_continuous(self) -> None:
        segments = [("lap", 300, 3.3, (140.0, 150.0)) for _ in range(9)]
        segments.append(("lap", 300, 2.5, (140.0, 130.0)))
        result = session_execution(_session(segments, kinds=False))
        self.assertEqual(result["structure"], "continuous")
        self.assertEqual(result["halves"]["status"], "ok")

    def test_adjacent_work_labels_are_one_continuous_effort(self) -> None:
        segments = [("work", 300, 3.5, (150.0, 160.0)) for _ in range(10)]
        result = session_execution(_session(segments))
        self.assertEqual(result["structure"], "continuous")
        self.assertIn("halves", result)

    def test_recovery_labelled_warm_up_and_cool_down(self) -> None:
        # Intervals.icu labels everything that is not work as recovery.
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("recovery", 900, 3.0, (120.0, 135.0))
        ]
        for rep in range(4):
            segments.append(("work", 240, 4.5, (150.0, 170.0)))
            segments.append(("recovery", 900 if rep == 3 else 120, 2.5, (170.0, 140.0)))
        result = session_execution(_session(segments))
        self.assertEqual(result["warmup"]["duration_s"], 900)
        self.assertEqual(result["cooldown"]["duration_s"], 900)
        self.assertEqual(
            [item["after_rep"] for item in result["recoveries"]], [1, 2, 3]
        )

    def test_standing_rests_still_split_into_work_and_rest(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = []
        for _ in range(5):
            segments += [
                ("lap", 240, 4.5, (150.0, 170.0)),
                ("lap", 120, 0.0, (170.0, 120.0)),
            ]
        session = _session(segments, kinds=False)
        speed = session["streams"]["velocity_smooth"]
        session["streams"]["moving"] = [value > 0 for value in speed]
        result = session_execution(session)
        self.assertEqual(result["structure"], "interval")
        self.assertEqual(result["structure_origin"], "lap_output")
        self.assertEqual(result["rep_summary"]["rep_count"], 5)

    def test_long_rep_lists_name_the_real_count(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = []
        for _ in range(50):
            segments += [
                ("work", 40, 5.0, (150.0, 165.0)),
                ("recovery", 40, 2.5, (165.0, 150.0)),
            ]
        result = session_execution(_session(segments))
        self.assertEqual(len(result["reps"]), 40)
        self.assertEqual(result["rep_summary"]["rep_count"], 50)
        self.assertEqual(result["rep_summary"]["reps_listed"], 40)

    def test_unsupported_or_short_sessions_say_why(self) -> None:
        swim = _session([("lap", 1800, 1.2, (130.0, 140.0))], sport="swim")
        self.assertEqual(session_execution(swim)["status"], "not_applicable")
        short = _session([("lap", 300, 3.0, (130.0, 140.0))])
        self.assertEqual(session_execution(short)["status"], "insufficient_data")
        no_output = _session([("lap", 1800, 3.0, (130.0, 140.0))])
        del no_output["streams"]["velocity_smooth"]
        self.assertEqual(
            session_execution(no_output)["reason"], "Tempo oder Leistung fehlt."
        )


if __name__ == "__main__":
    unittest.main()
