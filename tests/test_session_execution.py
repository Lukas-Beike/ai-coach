"""Lap-by-lap execution of one run or ride from synthetic streams."""

from __future__ import annotations

import unittest
from typing import Any

from session_stream_support import synthetic_session as _session

from backend.performance.session_execution import session_execution


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

    def test_rep_detail_shows_start_heart_rate_stride_and_terrain(self) -> None:
        session = _interval_run()
        streams = session["streams"]
        work = [lap for lap in session["laps"] if lap["kind"] == "work"]
        first = work[0]
        start = int(first["start_time"])
        # The first rep starts 30 s too fast and climbs 12 m.
        for second in range(start, start + 30):
            streams["velocity_smooth"][second] = 5.0
        streams["altitude"] = [100.0] * len(streams["time"])
        for index in range(start, int(first["end_time"]) + 1):
            streams["altitude"][index] = 100.0 + 12.0 * (index - start) / 180
        for index in range(int(first["end_time"]) + 1, len(streams["time"])):
            streams["altitude"][index] = 112.0
        session["lap_source"] = "device_laps"
        result = session_execution(session)
        rep = result["reps"][0]
        self.assertGreater(rep["start_change_pct"], 10)
        self.assertEqual(result["reps"][1]["start_change_pct"], 0.0)
        self.assertEqual(result["reps"][1]["variability_pct"], 0.0)
        self.assertEqual(rep["elevation_change_m"], 12.0)
        self.assertEqual(rep["stride_length_m"], 1.62)
        self.assertEqual(rep["heart_rate_peak"], 170)
        self.assertLess(rep["heart_rate_first_half"], rep["heart_rate_second_half"])
        self.assertEqual(rep["cadence_first_half"], 170)
        self.assertEqual(result["lap_source"], "device_laps")
        self.assertIn("heart_rate_end", result["recoveries"][0])
        self.assertEqual(result["rep_summary"]["stride_length_m_first"], 1.62)
        self.assertEqual(result["rep_summary"]["stride_length_m_last"], 1.48)

    def test_short_reps_with_lap_distance_get_a_lap_pace(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0))
        ]
        for _ in range(6):
            segments += [
                ("work", 50, 5.0, (150.0, 165.0)),
                ("recovery", 60, 2.5, (165.0, 150.0)),
            ]
        session = _session(segments)
        for lap in session["laps"]:
            if lap["kind"] == "work":
                lap["distance_m"] = 245.0
        rep = session_execution(session)["reps"][0]
        self.assertEqual(rep["lap_pace"], 204)
        self.assertEqual(rep["output"], 200)

    def test_indoor_rides_with_held_power_are_erg_like(self) -> None:
        segments = [
            ("warmup", 600, 150.0, (110.0, 125.0)),
            ("work", 480, 280.0, (150.0, 165.0)),
            ("recovery", 240, 120.0, (165.0, 130.0)),
            ("work", 480, 280.0, (150.0, 168.0)),
            ("cooldown", 300, 130.0, (130.0, 115.0)),
        ]
        indoor = _session(segments, sport="ride", output="watts", cadence=90.0)
        indoor["environment"] = "virtual"
        self.assertTrue(session_execution(indoor)["erg_like"])
        outdoor = _session(segments, sport="ride", output="watts", cadence=90.0)
        outdoor["environment"] = "outdoor"
        self.assertNotIn("erg_like", session_execution(outdoor))

    def test_short_labelled_rests_keep_the_session_an_interval_one(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0))
        ]
        for _ in range(10):
            segments += [
                ("work", 30, 5.5, (150.0, 170.0)),
                ("recovery", 15, 2.0, (170.0, 160.0)),
            ]
        result = session_execution(_session(segments))
        self.assertEqual(result["structure"], "interval")
        self.assertEqual(result["rep_summary"]["rep_count"], 10)

    def test_a_recovery_split_into_laps_counts_as_one(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0)),
            ("work", 180, 4.5, (150.0, 170.0)),
            ("recovery", 60, 0.5, (170.0, 140.0)),
            ("recovery", 120, 2.5, (140.0, 130.0)),
            ("work", 180, 4.5, (150.0, 170.0)),
            ("cooldown", 300, 2.8, (140.0, 125.0)),
        ]
        recovery = session_execution(_session(segments))["recoveries"][0]
        self.assertEqual(recovery["duration_s"], 180)
        self.assertEqual(recovery["heart_rate_end"], 130)

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
