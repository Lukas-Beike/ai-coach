"""Characterize recovery source precedence as the parity reference for refactors.

These tests pin current behavior for the recovery projections in
backend/performance, including quirks that are not necessarily intended. Quirks
are marked in comments so a refactor can review them rather than silently keep
them. They use fixed dates and in-memory payloads
only; no provider, storage, or network access is involved. Intervals.icu HRV
behavior is intentionally not covered here.
"""

import unittest
from datetime import date, timedelta
from typing import Any

from backend.performance.personal_recovery import personal_recovery
from backend.performance.planning_recovery import planning_recovery_by_date
from backend.performance.recovery_context import performance_recovery_context

TODAY = date(2026, 5, 4)
GARMIN = "Garmin Connect"
INTERVALS = "Intervals.icu Wellness"


def _garmin_record(day: str, **fields: Any) -> dict[str, Any]:
    return {"calendarDate": day, **fields}


def _wellness_row(day: str, **fields: Any) -> dict[str, Any]:
    return {"id": day, **fields}


def _garmin_nights(
    field: str,
    nights: int,
    *,
    value: float,
    latest_offset: int = 0,
    latest_value: float | None = None,
) -> list[dict[str, Any]]:
    """Return nights+1 Garmin records, the newest ending latest_offset days back."""
    records: list[dict[str, Any]] = []
    for index in range(nights + 1):
        day = TODAY - timedelta(days=latest_offset + index)
        use_latest = index == 0 and latest_value is not None
        records.append(
            _garmin_record(
                day.isoformat(), **{field: latest_value if use_latest else value}
            )
        )
    return records


def _garmin_baseline(result: dict[str, Any], metric: str) -> dict[str, Any]:
    return next(
        row
        for row in result["baselines"]
        if row["metric"] == metric and row["source"] == GARMIN
    )


class RecoveryContextPrecedenceTests(unittest.TestCase):
    def test_sleep_and_resting_hr_choose_sources_independently(self) -> None:
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=28_800)]}
        latest = {"restingHR": 56}
        rows = [_wellness_row("2026-05-03", restingHR=58)]

        result = performance_recovery_context(garmin, latest, rows, TODAY)

        self.assertEqual(result["sleep_source"], GARMIN)
        self.assertEqual(result["sleep_hours"], 8.0)
        self.assertEqual(result["resting_hr_source"], INTERVALS)
        self.assertEqual(result["resting_hr"], 56)
        self.assertEqual(result["resting_hr_average"], 58.0)
        self.assertIsNone(result["resting_hr_date"])

    def test_garmin_sleep_hours_key_sets_sleep_date_even_when_seconds_are_newer(
        self,
    ) -> None:
        # Quirk: the sleep_hours search and the seconds search run independently.
        # A dated sleep_hours record wins over a newer seconds record, and
        # sleep_date reports the sleep_hours record's date.
        garmin = {
            "sleep": [
                _garmin_record("2026-05-02", sleep_hours=6.5),
                _garmin_record("2026-05-04", sleepTimeSeconds=28_800),
            ]
        }

        result = performance_recovery_context(garmin, {}, [], TODAY)

        self.assertEqual(result["sleep_hours"], 6.5)
        self.assertEqual(result["sleep_date"], "2026-05-02")
        self.assertEqual(result["sleep_source"], GARMIN)
        self.assertEqual(result["sleep_average"], 8.0)

    def test_garmin_seconds_derived_sleep_has_no_sleep_date(self) -> None:
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=27_000)]}

        result = performance_recovery_context(garmin, {}, [], TODAY)

        self.assertEqual(result["sleep_hours"], 7.5)
        self.assertIsNone(result["sleep_date"])
        self.assertEqual(result["sleep_source"], GARMIN)

    def test_zero_garmin_sleep_is_a_present_value_and_does_not_fall_back(self) -> None:
        # Quirk: sleep duration has no plausibility bounds on the Garmin path, so
        # a zero-second night is a present value and blocks the Intervals fallback.
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=0)]}

        result = performance_recovery_context(garmin, {"sleepSecs": 25_200}, [], TODAY)

        self.assertEqual(result["sleep_hours"], 0.0)
        self.assertEqual(result["sleep_source"], GARMIN)

    def test_garmin_sleep_without_duration_defers_whole_sleep_block_to_intervals(
        self,
    ) -> None:
        # Quirk: a Garmin record with a sleep score but no duration does not
        # produce a Garmin sleep block, so Intervals supplies the score too.
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepScore=88)]}
        latest = {"sleepSecs": 25_200, "sleepScore": 70}

        result = performance_recovery_context(garmin, latest, [], TODAY)

        self.assertEqual(result["sleep_hours"], 7.0)
        self.assertEqual(result["sleep_source"], INTERVALS)
        self.assertEqual(result["sleep_score"], 70)
        self.assertEqual(result["sleep_score_source"], INTERVALS)

    def test_out_of_range_garmin_sleep_score_falls_back_to_intervals_score(
        self,
    ) -> None:
        garmin = {
            "sleep": [
                _garmin_record("2026-05-04", sleepTimeSeconds=28_800, sleepScore=120)
            ]
        }

        with_intervals = performance_recovery_context(
            garmin, {"sleepScore": 74}, [], TODAY
        )
        without_intervals = performance_recovery_context(garmin, {}, [], TODAY)

        self.assertEqual(with_intervals["sleep_source"], GARMIN)
        self.assertEqual(with_intervals["sleep_score"], 74)
        self.assertEqual(with_intervals["sleep_score_source"], INTERVALS)
        self.assertEqual(without_intervals["sleep_source"], GARMIN)
        self.assertIsNone(without_intervals["sleep_score"])
        self.assertIsNone(without_intervals["sleep_score_source"])

    def test_garmin_sleep_average_never_blends_in_intervals_history(self) -> None:
        rows = [
            _wellness_row("2026-05-01", sleepSecs=18_000),
            _wellness_row("2026-05-03", sleepSecs=18_000),
        ]
        in_window = {"sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=28_800)]}
        outside_window = {
            "sleep": [_garmin_record("2026-04-27", sleepTimeSeconds=28_800)]
        }

        recent = performance_recovery_context(in_window, {}, rows, TODAY)
        stale = performance_recovery_context(outside_window, {}, rows, TODAY)

        self.assertEqual(recent["sleep_average"], 8.0)
        # Quirk: Garmin values have no freshness window for the current value, so a
        # night from 7 days ago beats newer Intervals sleep (5 h on 2026-05-03).
        self.assertEqual(stale["sleep_hours"], 8.0)
        self.assertEqual(stale["sleep_source"], GARMIN)
        # Quirk: the Garmin average is None outside the 7-day window and does not
        # fall back to the Intervals rows that are inside it.
        self.assertIsNone(stale["sleep_average"])

    def test_out_of_bounds_garmin_resting_hr_uses_older_valid_garmin_first(
        self,
    ) -> None:
        # Quirk: an implausible latest Garmin value is skipped, not treated as
        # "no Garmin data", so an older valid Garmin value is used before Intervals.
        garmin = {
            "resting_hr": [
                _garmin_record("2026-05-04", restingHeartRate=15),
                _garmin_record("2026-05-02", restingHeartRate=48),
            ]
        }

        result = performance_recovery_context(
            garmin,
            {"restingHR": 56},
            [_wellness_row("2026-05-03", restingHR=54)],
            TODAY,
        )

        self.assertEqual(result["resting_hr"], 48)
        self.assertEqual(result["resting_hr_source"], GARMIN)
        self.assertEqual(result["resting_hr_date"], "2026-05-02")
        self.assertEqual(result["resting_hr_average"], 48.0)

    def test_out_of_bounds_only_garmin_resting_hr_falls_back_to_intervals(
        self,
    ) -> None:
        rows = [
            _wellness_row("2026-05-02", restingHR=58),
            _wellness_row("2026-05-04", restingHR=56),
        ]
        for implausible in (29, 231):
            with self.subTest(implausible=implausible):
                garmin = {
                    "resting_hr": [
                        _garmin_record("2026-05-04", restingHeartRate=implausible)
                    ]
                }

                result = performance_recovery_context(
                    garmin, {"restingHR": 56}, rows, TODAY
                )

                self.assertEqual(result["resting_hr"], 56)
                self.assertEqual(result["resting_hr_source"], INTERVALS)
                self.assertIsNone(result["resting_hr_date"])
                self.assertEqual(result["resting_hr_average"], 57.0)

    def test_plausibility_bounds_are_inclusive_at_their_edges(self) -> None:
        # Bounds come from garmin_bounded_metric: resting HR 30..230, sleep score 0..100.
        for resting_hr in (30, 230):
            with self.subTest(resting_hr=resting_hr):
                garmin = {
                    "resting_hr": [
                        _garmin_record("2026-05-04", restingHeartRate=resting_hr)
                    ]
                }

                result = performance_recovery_context(
                    garmin, {"restingHR": 56}, [], TODAY
                )

                self.assertEqual(result["resting_hr"], resting_hr)
                self.assertEqual(result["resting_hr_source"], GARMIN)
        for sleep_score in (0, 100):
            with self.subTest(sleep_score=sleep_score):
                garmin = {
                    "sleep": [
                        _garmin_record(
                            "2026-05-04",
                            sleepTimeSeconds=28_800,
                            sleepScore=sleep_score,
                        )
                    ]
                }

                result = performance_recovery_context(
                    garmin, {"sleepScore": 74}, [], TODAY
                )

                self.assertEqual(result["sleep_score"], sleep_score)
                self.assertEqual(result["sleep_score_source"], GARMIN)

    def test_garmin_resting_hr_average_is_not_backfilled_from_intervals(self) -> None:
        garmin = {"resting_hr": [_garmin_record("2026-04-27", restingHeartRate=50)]}

        result = performance_recovery_context(
            garmin, {}, [_wellness_row("2026-05-03", restingHR=60)], TODAY
        )

        # Quirk: a 7-day-old Garmin value beats newer Intervals resting HR (60), and
        # the average stays None instead of using the Intervals row.
        self.assertEqual(result["resting_hr"], 50)
        self.assertEqual(result["resting_hr_source"], GARMIN)
        self.assertEqual(result["resting_hr_date"], "2026-04-27")
        self.assertIsNone(result["resting_hr_average"])

    def test_readiness_uses_first_present_intervals_key_even_when_unparseable(
        self,
    ) -> None:
        # Quirk: the first non-empty readiness key wins even when it cannot be
        # parsed, so a valid readinessScore later in the list is never considered.
        latest = {"readiness": {"label": "unknown"}, "readinessScore": 81}
        garmin = {"readiness": [_garmin_record("2026-05-04", score=64)]}

        result = performance_recovery_context(garmin, latest, [], TODAY)

        self.assertEqual(result["readiness"], 64)
        self.assertEqual(result["readiness_source"], GARMIN)
        self.assertIsNone(result["readiness_average"])

    def test_readiness_average_is_always_the_intervals_rows(self) -> None:
        garmin = {"readiness": [_garmin_record("2026-05-04", score=60)]}
        rows = [_wellness_row("2026-05-01", readiness=70)]

        intervals_current = performance_recovery_context(
            garmin, {"readiness": 72}, rows, TODAY
        )
        garmin_current = performance_recovery_context(garmin, {}, rows, TODAY)

        self.assertEqual(intervals_current["readiness"], 72)
        self.assertEqual(intervals_current["readiness_source"], INTERVALS)
        self.assertEqual(intervals_current["readiness_average"], 70.0)
        self.assertEqual(garmin_current["readiness"], 60)
        self.assertEqual(garmin_current["readiness_source"], GARMIN)
        self.assertEqual(garmin_current["readiness_average"], 70.0)


class PlanningRecoveryPrecedenceTests(unittest.TestCase):
    def test_garmin_overwrites_intervals_sleep_and_resting_hr_without_bounds(
        self,
    ) -> None:
        # Quirk: planning applies no plausibility bounds to Garmin overwrites,
        # unlike the performance recovery context and personal baselines.
        wellness = [
            _wellness_row("2026-05-04", sleepSecs=25_200, sleepScore=70, restingHR=55)
        ]
        garmin = {
            "sleep": [
                _garmin_record("2026-05-04", sleepTimeSeconds=90_000, sleepScore=150)
            ],
            "resting_hr": [_garmin_record("2026-05-04", restingHeartRate=15)],
        }

        day = planning_recovery_by_date(wellness, garmin, {}, None)["2026-05-04"]

        self.assertEqual(day["sleep_hours"], 25.0)
        self.assertEqual(day["sleep_score"], 150)
        self.assertEqual(day["resting_hr"], 15)
        self.assertEqual(
            day["sources"],
            {"sleep_hours": GARMIN, "sleep_score": GARMIN, "resting_hr": GARMIN},
        )

    def test_garmin_zero_sleep_seconds_overwrites_intervals_sleep_hours(self) -> None:
        # Quirk: zero seconds are not treated as missing, so they overwrite.
        wellness = [_wellness_row("2026-05-04", sleepSecs=25_200)]
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=0)]}

        day = planning_recovery_by_date(wellness, garmin, {}, None)["2026-05-04"]

        self.assertEqual(day["sleep_hours"], 0.0)
        self.assertEqual(day["sources"]["sleep_hours"], GARMIN)

    def test_garmin_sleep_hours_text_takes_precedence_over_seconds(self) -> None:
        garmin = {
            "sleep": [
                _garmin_record("2026-05-04", sleep_hours="7,5", sleepTimeSeconds=28_800)
            ]
        }

        day = planning_recovery_by_date([], garmin, {}, None)["2026-05-04"]

        self.assertEqual(day["sleep_hours"], 7.5)

    def test_readiness_only_fills_days_without_an_intervals_value(self) -> None:
        wellness = [
            _wellness_row("2026-05-04", readiness=80),
            _wellness_row("2026-05-05"),
        ]
        garmin = {
            "readiness": [
                _garmin_record("2026-05-04", score=65),
                _garmin_record("2026-05-05", score=61),
                _garmin_record("2026-05-06", score=58),
            ]
        }

        result = planning_recovery_by_date(wellness, garmin, {}, None)

        self.assertEqual(result["2026-05-04"]["readiness"], 80)
        self.assertEqual(result["2026-05-04"]["sources"]["readiness"], INTERVALS)
        self.assertEqual(result["2026-05-05"]["readiness"], 61)
        self.assertEqual(result["2026-05-05"]["sources"]["readiness"], GARMIN)
        self.assertEqual(result["2026-05-06"]["readiness"], 58)
        self.assertEqual(result["2026-05-06"]["sources"]["readiness"], GARMIN)

    def test_intervals_day_without_metrics_is_kept_as_empty_entry(self) -> None:
        # Quirk: a dated row with no usable metric still creates an empty day.
        result = planning_recovery_by_date([_wellness_row("2026-05-06")], {}, {}, None)

        self.assertEqual(result, {"2026-05-06": {}})

    def test_saved_battery_keeps_raw_values_and_ready_morning_overrides(self) -> None:
        # Quirk: saved history values keep their raw type ("72" stays a string).
        history = {"2026-05-02": "72", "2026-05-03": 70, "2026-05-04": "n/a"}
        morning = {
            "status": "ready",
            "sleep_date": "2026-05-04",
            "morning": {"value": 66},
        }

        result = planning_recovery_by_date([], {}, history, morning)

        self.assertEqual(result["2026-05-02"]["body_battery"], "72")
        self.assertEqual(result["2026-05-03"]["body_battery"], 70)
        self.assertEqual(result["2026-05-04"]["body_battery"], 66)
        self.assertEqual(result["2026-05-04"]["sources"]["body_battery"], GARMIN)

    def test_ready_morning_value_is_stored_without_numeric_validation(self) -> None:
        # Quirk: the ready morning value is not checked as a number, unlike
        # saved history values, so a text value overwrites the saved one.
        morning = {
            "status": "ready",
            "sleep_date": "2026-05-04",
            "morning": {"value": "n/a"},
        }

        result = planning_recovery_by_date([], {}, {"2026-05-04": 70}, morning)

        self.assertEqual(result["2026-05-04"]["body_battery"], "n/a")

    def test_non_ready_or_incomplete_morning_battery_keeps_saved_value(self) -> None:
        history = {"2026-05-04": 70}
        incomplete = (
            {"status": "pending", "sleep_date": "2026-05-04", "morning": {"value": 40}},
            {
                "status": "ready",
                "sleep_date": "2026-05-04",
                "morning": {"value": None},
            },
            {"status": "ready", "morning": {"value": 40}},
        )
        for morning in incomplete:
            with self.subTest(morning=morning):
                result = planning_recovery_by_date([], {}, history, morning)

                self.assertEqual(result["2026-05-04"]["body_battery"], 70)


class PersonalRecoveryGarminTests(unittest.TestCase):
    today = TODAY

    def test_garmin_resting_hr_thresholds_and_current_night_excluded(self) -> None:
        for nights, status in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (27, "provisional"),
            (28, "ok"),
        ):
            with self.subTest(nights=nights):
                records = _garmin_nights(
                    "restingHeartRate", nights, value=50, latest_value=100
                )

                result = personal_recovery([], {"resting_hr": records}, {}, self.today)
                baseline = _garmin_baseline(result, "resting_hr")

                self.assertEqual(baseline["status"], status)
                self.assertEqual(baseline["nights"], nights)
                self.assertEqual(baseline["measurement"], "restingHeartRate")
                self.assertEqual(baseline["unit"], "bpm")
                self.assertEqual(baseline["value"], 100)
                if status == "insufficient_data":
                    self.assertEqual(
                        baseline["reason"],
                        "Mindestens 14 frühere passende Nächte erforderlich.",
                    )
                else:
                    self.assertEqual(baseline["median"], 50)
                    self.assertEqual(baseline["position"], "above")

    def test_garmin_sleep_thresholds_and_below_position(self) -> None:
        for nights, status in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (27, "provisional"),
            (28, "ok"),
        ):
            with self.subTest(nights=nights):
                records = _garmin_nights(
                    "sleepTimeSeconds",
                    nights,
                    value=7 * 3600,
                    latest_value=6 * 3600,
                )

                result = personal_recovery([], {"sleep": records}, {}, self.today)
                baseline = _garmin_baseline(result, "sleep")

                self.assertEqual(baseline["status"], status)
                self.assertEqual(baseline["nights"], nights)
                self.assertEqual(baseline["measurement"], "sleepTimeSeconds")
                self.assertEqual(baseline["unit"], "h")
                self.assertEqual(baseline["value"], 6.0)
                if status != "insufficient_data":
                    self.assertEqual(baseline["median"], 7.0)
                    self.assertEqual(baseline["position"], "below")

    def test_implausible_latest_values_are_dropped_before_baselines(self) -> None:
        # Quirk: values rejected by the plausibility bounds are removed from the
        # series, so the previous valid night becomes the observed value.
        cases = (
            ("restingHeartRate", "resting_hr", 15, 50),
            ("sleepTimeSeconds", "sleep", 25 * 3600, 7 * 3600),
        )
        for field, section, implausible, valid in cases:
            with self.subTest(field=field):
                records = _garmin_nights(
                    field, 20, value=valid, latest_value=implausible
                )

                result = personal_recovery([], {section: records}, {}, self.today)
                baseline = _garmin_baseline(
                    result, "resting_hr" if section == "resting_hr" else "sleep"
                )

                self.assertEqual(baseline["observed_at"], "2026-05-03")
                self.assertEqual(baseline["status"], "provisional")
                self.assertNotIn(
                    "2026-05-04", [point["date"] for point in baseline["history"]]
                )

    def test_stale_garmin_measurement_is_not_classified_even_with_history(
        self,
    ) -> None:
        # Quirk: a measurement older than yesterday blocks classification even
        # when enough earlier nights exist, and no median is reported.
        records = _garmin_nights("restingHeartRate", 30, value=50, latest_offset=2)

        result = personal_recovery([], {"resting_hr": records}, {}, self.today)
        baseline = _garmin_baseline(result, "resting_hr")

        self.assertEqual(baseline["status"], "insufficient_data")
        self.assertEqual(baseline["reason"], "Messung veraltet.")
        self.assertEqual(baseline["nights"], 30)
        self.assertNotIn("median", baseline)

    def test_yesterday_measurement_still_counts_as_current(self) -> None:
        records = _garmin_nights("restingHeartRate", 28, value=50, latest_offset=1)

        result = personal_recovery([], {"resting_hr": records}, {}, self.today)

        self.assertEqual(_garmin_baseline(result, "resting_hr")["status"], "ok")

    def test_garmin_history_keeps_83_days_and_compares_against_42_nights(
        self,
    ) -> None:
        records = _garmin_nights("restingHeartRate", 90, value=50)

        result = personal_recovery([], {"resting_hr": records}, {}, self.today)
        baseline = _garmin_baseline(result, "resting_hr")

        self.assertEqual(len(baseline["history"]), 84)
        self.assertEqual(
            baseline["history"][0]["date"], (TODAY - timedelta(days=83)).isoformat()
        )
        self.assertEqual(baseline["nights"], 42)

    def test_garmin_sleep_deficit_uses_seven_known_nights(self) -> None:
        records = _garmin_nights("sleepTimeSeconds", 6, value=6 * 3600)

        result = personal_recovery(
            [], {"sleep": records}, {"sleep_target_hours": 8}, self.today
        )

        self.assertEqual(
            result["sleep_deficits"],
            [
                {
                    "source": GARMIN,
                    "measurement": "sleepTimeSeconds",
                    "known_nights": 7,
                    "target_hours": 8.0,
                    "deficit_hours": 14.0,
                    "status": "ok",
                }
            ],
        )

    def test_sleep_target_bounds_and_falsy_zero_target(self) -> None:
        # Quirk: a numeric 0 target is falsy and therefore treated as missing.
        records = _garmin_nights("sleepTimeSeconds", 6, value=6 * 3600)
        cases: tuple[tuple[Any, float | None, list[Any]], ...] = (
            (0, None, []),
            (13, 13.0, []),
            ("abc", None, []),
        )
        for raw, expected_target, expected_deficits in cases:
            with self.subTest(target=raw):
                result = personal_recovery(
                    [], {"sleep": records}, {"sleep_target_hours": raw}, self.today
                )

                self.assertEqual(result["sleep_target_hours"], expected_target)
                self.assertEqual(result["sleep_deficits"], expected_deficits)

    def test_sleep_target_edges_four_and_twelve_hours_are_accepted(self) -> None:
        records = _garmin_nights("sleepTimeSeconds", 6, value=6 * 3600)
        for target, deficit_hours in ((4, 0.0), (12, 42.0)):
            with self.subTest(target=target):
                result = personal_recovery(
                    [], {"sleep": records}, {"sleep_target_hours": target}, self.today
                )

                self.assertEqual(
                    result["sleep_deficits"][0]["deficit_hours"], deficit_hours
                )

    def test_plausibility_bounds_are_inclusive_at_their_edges(self) -> None:
        # Personal bounds: resting HR accepted from 20 to 230 bpm; sleep up to 24 h.
        cases = (
            ("restingHeartRate", "resting_hr", 50, 20, 20),
            ("restingHeartRate", "resting_hr", 50, 230, 230),
            ("sleepTimeSeconds", "sleep", 7 * 3600, 24 * 3600, 24.0),
        )
        for field, section, past_value, latest_value, expected in cases:
            with self.subTest(field=field, latest=latest_value):
                records = _garmin_nights(
                    field, 20, value=past_value, latest_value=latest_value
                )

                result = personal_recovery([], {section: records}, {}, self.today)
                baseline = _garmin_baseline(
                    result, "resting_hr" if section == "resting_hr" else "sleep"
                )

                self.assertEqual(baseline["observed_at"], TODAY.isoformat())
                self.assertEqual(baseline["value"], expected)


if __name__ == "__main__":
    unittest.main()
