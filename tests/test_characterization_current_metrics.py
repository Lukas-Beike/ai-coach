"""Characterize current source precedence of ``current_performance_metrics``.

These tests pin today's behavior, including quirks, as the parity reference for
a later refactor. Quirks are marked with a "Quirk:" comment. Note text is not
asserted because it is not part of the precedence contract.
"""

import unittest
from datetime import date
from typing import Any

from backend.performance.current_metrics import current_performance_metrics
from backend.performance.garmin_metrics import garmin_performance_metrics

TODAY = date(2026, 5, 4)
GARMIN = "Garmin Connect"
WELLNESS = "Intervals.icu Wellness"
INTERVALS = "Intervals.icu"
INTERVALS_GENERIC = "Intervals.icu (allgemein)"
PROFILE = "Manuell"

RACE_KEYS = (
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)


def _garmin(raw: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return garmin_performance_metrics(raw or {}, TODAY)


def _snapshot(
    athlete: dict[str, Any] | None = None,
    wellness: list[dict[str, Any]] | None = None,
    activities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "athlete": athlete or {},
        "recent_wellness": wellness or [],
        "recent_activities": activities or [],
    }


def _current(
    snapshot: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    garmin: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    return current_performance_metrics(
        snapshot or _snapshot(),
        profile or {},
        garmin if garmin is not None else _garmin(),
    )


def _setting(activity_type: str, **fields: Any) -> dict[str, Any]:
    return {"types": [activity_type], **fields}


def _wellness(day: str, **fields: Any) -> dict[str, Any]:
    return {"id": day, **fields}


def _pair(metric: dict[str, Any]) -> tuple[Any, Any]:
    return metric["value"], metric["source"]


def _garmin_weight(day: str, grams: int) -> dict[str, Any]:
    return {
        "dailyWeightSummaries": [
            {
                "summaryDate": day,
                "latestWeight": {"weight": grams, "bodyFat": 12.0},
            }
        ]
    }


class CurrentWeightChainTests(unittest.TestCase):
    def test_garmin_weight_wins_over_intervals_and_profile(self) -> None:
        garmin = _garmin({"weight": _garmin_weight("2026-05-03", 72800)})
        result = _current(
            _snapshot(
                athlete={"weight": 80},
                wellness=[_wellness("2026-05-03", weight=79)],
            ),
            {"weight_kg": 81},
            garmin,
        )
        self.assertEqual(result["weight_kg"], garmin["weight_kg"])
        self.assertEqual(_pair(result["weight_kg"]), (72.8, GARMIN))
        self.assertEqual(result["weight_kg"]["unit"], "kg")

    def test_garmin_latest_dated_weight_is_used_regardless_of_list_order(
        self,
    ) -> None:
        garmin = _garmin(
            {
                "weight": {
                    "dailyWeightSummaries": [
                        {
                            "summaryDate": "2026-05-01",
                            "latestWeight": {"weight": 73000},
                        },
                        {
                            "summaryDate": "2026-05-03",
                            "latestWeight": {"weight": 71000},
                        },
                    ]
                }
            }
        )
        result = _current(garmin=garmin)
        self.assertEqual(_pair(result["weight_kg"]), (71.0, GARMIN))

    def test_old_garmin_weight_still_wins_over_newer_wellness(self) -> None:
        # Quirk: Garmin weight is not compared by date with Intervals wellness,
        # so a 2026-04-01 Garmin weight beats the 2026-05-03 wellness weight.
        garmin = _garmin({"weight": _garmin_weight("2026-04-01", 71500)})
        result = _current(
            _snapshot(wellness=[_wellness("2026-05-03", weight=78)]),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["weight_kg"]), (71.5, GARMIN))

    def test_weight_falls_back_wellness_then_athlete_then_profile(self) -> None:
        cases = (
            (
                "wellness",
                _snapshot(
                    athlete={"weight": 80},
                    wellness=[_wellness("2026-05-03", weight=78)],
                ),
                (78, WELLNESS),
            ),
            ("athlete", _snapshot(athlete={"weight": 80}), (80, INTERVALS)),
            ("profile", _snapshot(), (81, PROFILE)),
        )
        for name, snapshot, expected in cases:
            with self.subTest(source=name):
                result = _current(snapshot, {"weight_kg": 81})
                self.assertEqual(_pair(result["weight_kg"]), expected)

    def test_weight_is_empty_without_any_source(self) -> None:
        result = _current()
        self.assertEqual(_pair(result["weight_kg"]), (None, None))
        self.assertEqual(result["weight_kg"]["unit"], "kg")

    def test_weight_accepts_comma_decimal_and_skips_invalid_wellness(self) -> None:
        result = _current(
            _snapshot(
                athlete={"weight": 79},
                wellness=[_wellness("2026-05-03", weight="78,5")],
            )
        )
        self.assertEqual(_pair(result["weight_kg"]), (78.5, WELLNESS))

        result = _current(
            _snapshot(
                athlete={"weight": 79},
                wellness=[_wellness("2026-05-03", weight="invalid")],
            )
        )
        self.assertEqual(_pair(result["weight_kg"]), (79, INTERVALS))

    def test_latest_wellness_row_is_the_maximum_string_id(self) -> None:
        rows = [
            _wellness("2026-05-01", weight=80),
            _wellness("2026-05-03", weight=78),
            _wellness("2026-05-02", weight=79),
        ]
        result = _current(_snapshot(wellness=rows), {"weight_kg": 81})
        self.assertEqual(_pair(result["weight_kg"]), (78, WELLNESS))

    def test_wellness_ids_compare_as_strings_so_unpadded_dates_win(self) -> None:
        # Quirk: "2026-5-9" > "2026-05-10" as strings, so the unpadded id is
        # treated as the latest row.
        rows = [
            _wellness("2026-05-10", weight=78),
            _wellness("2026-5-9", weight=77),
        ]
        result = _current(_snapshot(wellness=rows))
        self.assertEqual(_pair(result["weight_kg"]), (77, WELLNESS))

    def test_only_latest_wellness_row_is_read_for_weight(self) -> None:
        # Quirk: an older wellness row with a weight is not used when the newest
        # row has none; the chain falls through to the athlete weight instead.
        rows = [_wellness("2026-05-01", weight=80), _wellness("2026-05-02")]
        result = _current(_snapshot(athlete={"weight": 79}, wellness=rows))
        self.assertEqual(_pair(result["weight_kg"]), (79, INTERVALS))

    def test_zero_wellness_weight_is_a_present_value(self) -> None:
        # Quirk: zero is accepted as a present value and beats the profile.
        result = _current(
            _snapshot(wellness=[_wellness("2026-05-03", weight=0)]),
            {"weight_kg": 81},
        )
        self.assertEqual(_pair(result["weight_kg"]), (0, WELLNESS))


class CurrentBodyMetricTests(unittest.TestCase):
    def test_body_fat_ignores_garmin_weight_payload_body_fat(self) -> None:
        garmin = _garmin({"weight": _garmin_weight("2026-05-03", 72800)})
        result = _current(garmin=garmin)
        self.assertEqual(_pair(result["body_fat_pct"]), (None, None))

    def test_body_fat_follows_wellness_athlete_then_profile(self) -> None:
        cases = (
            (
                "wellness bodyFat",
                _snapshot(wellness=[_wellness("2026-05-03", bodyFat=17)]),
                (17, WELLNESS),
            ),
            (
                "wellness body_fat",
                _snapshot(wellness=[_wellness("2026-05-03", body_fat=16)]),
                (16, WELLNESS),
            ),
            (
                "athlete bodyFat",
                _snapshot(athlete={"bodyFat": 18}),
                (18, INTERVALS),
            ),
            (
                "athlete body_fat",
                _snapshot(athlete={"body_fat": 19}),
                (19, INTERVALS),
            ),
            ("profile", _snapshot(), (20, PROFILE)),
        )
        for name, snapshot, expected in cases:
            with self.subTest(source=name):
                result = _current(snapshot, {"body_fat_pct": 20})
                self.assertEqual(_pair(result["body_fat_pct"]), expected)

    def test_body_fat_is_rounded_to_two_decimals_and_has_percent_unit(self) -> None:
        result = _current(
            _snapshot(wellness=[_wellness("2026-05-03", bodyFat="18.426")])
        )
        self.assertEqual(_pair(result["body_fat_pct"]), (18.43, WELLNESS))
        self.assertEqual(result["body_fat_pct"]["unit"], "%")

    def test_height_is_converted_from_metres_to_centimetres(self) -> None:
        cases = ((1.2, 120), (1.8, 180), (2.5, 250), ("1,75", 175), (180, 180))
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = _current(_snapshot(athlete={"height": raw}))
                self.assertEqual(_pair(result["height_cm"]), (expected, INTERVALS))
                self.assertEqual(result["height_cm"]["unit"], "cm")

    def test_height_outside_metre_band_is_not_converted_quirk(self) -> None:
        # Quirk: values just outside 1.2-2.5 are left as-is and reported in cm.
        for raw in (1.19, 2.51):
            with self.subTest(raw=raw):
                result = _current(_snapshot(athlete={"height": raw}))
                self.assertEqual(result["height_cm"]["value"], raw)

    def test_height_cm_key_wins_over_height_and_profile_is_fallback(self) -> None:
        result = _current(_snapshot(athlete={"height_cm": 170, "height": 1.8}))
        self.assertEqual(_pair(result["height_cm"]), (170, INTERVALS))

        result = _current(_snapshot(athlete={"height": "nan"}), {"height_cm": 175})
        self.assertEqual(_pair(result["height_cm"]), (175, PROFILE))

    def test_profile_height_in_metres_is_converted_quirk(self) -> None:
        # Quirk: the metre-to-cm conversion is also applied to the local profile.
        result = _current(_snapshot(), {"height_cm": 1.75})
        self.assertEqual(_pair(result["height_cm"]), (175, PROFILE))

        result = _current()
        self.assertEqual(_pair(result["height_cm"]), (None, None))


class CurrentThresholdTests(unittest.TestCase):
    def test_cycling_ftp_garmin_then_ride_then_wellness_then_athlete(self) -> None:
        garmin = _garmin({"cycling_ftp": {"functionalThresholdPower": 302}})
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", ftp=250)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (302, GARMIN))

        for invalid in (49, 701):
            with self.subTest(invalid=invalid):
                result = _current(
                    _snapshot(athlete={"sport_settings": [_setting("Ride", ftp=250)]}),
                    garmin=_garmin(
                        {"cycling_ftp": {"functionalThresholdPower": invalid}}
                    ),
                )
                self.assertEqual(_pair(result["cycling_ftp_watts"]), (250, INTERVALS))

        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", ftp=250, indoor_ftp=240)]}
            )
        )
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (250, INTERVALS))

        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", indoor_ftp=240)]},
                wellness=[
                    _wellness(
                        "2026-05-03", sport_info=[{"types": ["Ride"], "ftp": 255}]
                    )
                ],
            )
        )
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (240, INTERVALS))

    def test_wellness_ftp_is_labelled_as_intervals_not_wellness_quirk(self) -> None:
        # Quirk: a wellness-sourced FTP carries the plain "Intervals.icu" label.
        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Ride"], "ftp": 255}],
                    )
                ]
            )
        )
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (255, INTERVALS))

    def test_athlete_icu_ftp_is_last_cycling_fallback(self) -> None:
        result = _current(_snapshot(athlete={"icu_ftp": 240}))
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (240, INTERVALS))

    def test_first_matching_sport_setting_wins_even_without_value_quirk(self) -> None:
        # Quirk: the first Ride-matching setting is used even when it has no FTP;
        # a later "Rad" setting with FTP is ignored.
        athlete = {
            "icu_ftp": 240,
            "sport_settings": [_setting("Ride"), _setting("Rad", ftp=300)],
        }
        result = _current(_snapshot(athlete=athlete))
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (240, INTERVALS))

    def test_run_threshold_watts_never_uses_athlete_icu_ftp(self) -> None:
        # Quirk: the athlete-level icu_ftp does not feed run threshold power.
        result = _current(_snapshot(athlete={"icu_ftp": 240}))
        self.assertEqual(_pair(result["run_threshold_watts"]), (None, None))

        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Run", ftp=280)]})
        )
        self.assertEqual(_pair(result["run_threshold_watts"]), (280, INTERVALS))

        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "ftp": 285}],
                    )
                ]
            )
        )
        self.assertEqual(_pair(result["run_threshold_watts"]), (285, INTERVALS))

        garmin = _garmin(
            {"running_threshold": {"power": {"functionalThresholdPower": 328}}}
        )
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Run", ftp=280)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["run_threshold_watts"]), (328, GARMIN))

    def test_run_threshold_pace_converts_metres_per_second(self) -> None:
        cases = ((4.0, 250), (3.5, 286))
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = _current(
                    _snapshot(
                        athlete={
                            "sport_settings": [_setting("Run", threshold_pace=raw)]
                        }
                    )
                )
                self.assertEqual(
                    result["run_threshold_pace_seconds_per_km"]["value"], expected
                )

    def test_run_threshold_pace_boundary_and_string_quirks(self) -> None:
        # Quirk: only values below 20 are read as m/s; 20 and above pass through
        # unchanged as s/km, so 19.99 (about 50) and 20 (20) are discontinuous.
        # Quirk: a "4:27" string is not parsed and yields no value.
        # Quirk: negative values are rejected.
        cases = ((20, 20), (250, 250), (-4.0, None), ("4:27", None))
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = _current(
                    _snapshot(
                        athlete={
                            "sport_settings": [_setting("Run", threshold_pace=raw)]
                        }
                    )
                )
                self.assertEqual(
                    result["run_threshold_pace_seconds_per_km"]["value"], expected
                )

    def test_run_threshold_pace_wellness_fallback_and_garmin_override(self) -> None:
        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "threshold_pace": 4.0}],
                    )
                ]
            )
        )
        self.assertEqual(
            _pair(result["run_threshold_pace_seconds_per_km"]), (250, INTERVALS)
        )

        garmin = _garmin({"running_threshold": {"speedInMetersPerSecond": 4.0}})
        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Run", threshold_pace=3.5)]}
            ),
            garmin=garmin,
        )
        self.assertEqual(
            _pair(result["run_threshold_pace_seconds_per_km"]), (250, GARMIN)
        )

    def test_zone2_pace_aliases_and_wellness_fallback(self) -> None:
        # Values below 20 are read as m/s; 5.0 m/s is converted to 200 s/km.
        for key in (
            "zone2_pace",
            "zone_2_pace",
            "z2_pace",
            "pace_zone2",
            "paceZone2",
            "zone2Pace",
        ):
            with self.subTest(key=key):
                result = _current(
                    _snapshot(
                        athlete={"sport_settings": [_setting("Run", **{key: 5.0})]}
                    )
                )
                self.assertEqual(
                    _pair(result["run_zone2_pace_seconds_per_km"]), (200, INTERVALS)
                )

        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "zone2Pace": 300}],
                    )
                ]
            )
        )
        self.assertEqual(
            _pair(result["run_zone2_pace_seconds_per_km"]), (300, INTERVALS)
        )

    def test_zone2_pace_inclusive_second_bounds(self) -> None:
        for value, expected in ((119, None), (120, 120), (1800, 1800), (1801, None)):
            with self.subTest(value=value):
                result = _current(
                    _snapshot(
                        athlete={"sport_settings": [_setting("Run", zone2_pace=value)]}
                    )
                )
                self.assertEqual(
                    result["run_zone2_pace_seconds_per_km"]["value"], expected
                )

    def test_threshold_hr_sport_then_generic_labels(self) -> None:
        athlete = {"lthr": 165, "sport_settings": [_setting("Run", lthr=170)]}
        result = _current(_snapshot(athlete=athlete))
        self.assertEqual(_pair(result["run_threshold_hr_bpm"]), (170, INTERVALS))
        self.assertEqual(
            _pair(result["bike_threshold_hr_bpm"]), (165, INTERVALS_GENERIC)
        )

        result = _current(_snapshot(athlete={"lthr": 165}))
        self.assertEqual(
            _pair(result["bike_threshold_hr_bpm"]), (165, INTERVALS_GENERIC)
        )
        self.assertEqual(
            _pair(result["run_threshold_hr_bpm"]), (165, INTERVALS_GENERIC)
        )

        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", lthr=160)]},
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "lthr": 166}],
                    )
                ],
            )
        )
        self.assertEqual(_pair(result["bike_threshold_hr_bpm"]), (160, INTERVALS))
        self.assertEqual(_pair(result["run_threshold_hr_bpm"]), (166, INTERVALS))

        result = _current()
        self.assertEqual(_pair(result["bike_threshold_hr_bpm"]), (None, None))

    def test_threshold_hr_garmin_override_uses_running_threshold(self) -> None:
        garmin = _garmin(
            {
                "running_threshold": {
                    "speed_and_heart_rate": {
                        "speed": 3.8,
                        "heartRate": 176,
                        "heartRateCycling": 169,
                    }
                }
            }
        )
        result = _current(
            _snapshot(athlete={"lthr": 165}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["run_threshold_hr_bpm"]), (176, GARMIN))
        self.assertEqual(_pair(result["bike_threshold_hr_bpm"]), (169, GARMIN))


class CurrentMaxHrTests(unittest.TestCase):
    def test_sport_setting_max_hr_key_aliases(self) -> None:
        for key in ("max_hr", "maxHR", "maxHeartRate", "max_heartrate"):
            with self.subTest(key=key):
                result = _current(
                    _snapshot(
                        athlete={"sport_settings": [_setting("Ride", **{key: 190})]}
                    )
                )
                self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (190, INTERVALS))

    def test_out_of_range_setting_falls_through_to_wellness(self) -> None:
        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", max_hr=300)]},
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Ride"], "max_hr": 188}],
                    )
                ],
            )
        )
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (188, WELLNESS))

    def test_activity_maximum_is_next_then_athlete_profile(self) -> None:
        activities = [
            {"type": "Ride", "start_date_local": "2026-05-01", "maxHR": 181},
            {"type": "Ride", "start_date_local": "2026-05-02", "maxHR": 195},
            {"type": "Ride", "start_date_local": "2026-05-03", "maxHR": 400},
            {"type": "Run", "start_date_local": "2026-05-03", "maxHR": 210},
        ]
        result = _current(
            _snapshot(athlete={"max_hr": 200}, activities=activities),
        )
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (195, INTERVALS))
        self.assertEqual(_pair(result["running_max_hr_bpm"]), (210, INTERVALS))

        result = _current(_snapshot(athlete={"max_hr": 186}))
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (186, INTERVALS))

    def test_athlete_max_hr_outside_range_is_ignored(self) -> None:
        result = _current(_snapshot(athlete={"max_hr": 300}))
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (None, None))
        self.assertEqual(_pair(result["running_max_hr_bpm"]), (None, None))

    def test_garmin_profile_max_hr_overrides_intervals(self) -> None:
        garmin = _garmin(
            {
                "heart_rate_zones": [
                    {"sport": "CYCLING", "maxHeartRateUsed": 186},
                    {"sport": "RUNNING", "maxHeartRateUsed": 190},
                ]
            }
        )
        result = _current(_snapshot(athlete={"max_hr": 200}), garmin=garmin)
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (186, GARMIN))
        self.assertEqual(_pair(result["running_max_hr_bpm"]), (190, GARMIN))


class CurrentEftpTests(unittest.TestCase):
    def test_eftp_setting_then_wellness_then_latest_ride_activity(self) -> None:
        activity = {"type": "Ride", "start_date_local": "2026-05-03", "icu_eftp": 270}
        wellness = [
            _wellness("2026-05-03", sport_info=[{"types": ["Ride"], "eFTP": 265}])
        ]
        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", eFTP=262)]},
                wellness=wellness,
                activities=[activity],
            )
        )
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (262, INTERVALS))

        result = _current(_snapshot(wellness=wellness, activities=[activity]))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (265, INTERVALS))

        result = _current(_snapshot(activities=[activity]))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (270, INTERVALS))

    def test_latest_ride_is_chosen_by_start_date_not_list_order(self) -> None:
        activities = [
            {"type": "Ride", "start_date_local": "2026-05-03", "icu_eftp": 275},
            {"type": "Ride", "start_date_local": "2026-05-01", "icu_eftp": 270},
        ]
        result = _current(_snapshot(activities=list(reversed(activities))))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (275, INTERVALS))

    def test_latest_ride_without_eftp_hides_older_ride_quirk(self) -> None:
        # Quirk: the newest ride is selected first; if it has no eFTP, an older
        # ride's eFTP is not used.
        activities: list[dict[str, Any]] = [
            {"type": "Ride", "start_date_local": "2026-05-03"},
            {"type": "Ride", "start_date_local": "2026-05-01", "icu_eftp": 270},
        ]
        result = _current(_snapshot(activities=activities))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (None, None))

    def test_first_present_activity_type_decides_ride_quirk(self) -> None:
        # Quirk: only the first present field among type/sport/name is classified,
        # so a Run typed activity named "Morning Ride" is not a ride.
        activities = [
            {
                "type": "Run",
                "name": "Morning Ride",
                "start_date_local": "2026-05-03",
                "icu_eftp": 300,
            },
            {"type": "Ride", "start_date_local": "2026-05-01", "icu_eftp": 270},
        ]
        result = _current(_snapshot(activities=activities))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (270, INTERVALS))

    def test_activity_icu_eftp_key_precedes_eftp(self) -> None:
        activity = {
            "type": "Ride",
            "start_date_local": "2026-05-03",
            "icu_eftp": 275,
            "eftp": 999,
        }
        result = _current(_snapshot(activities=[activity]))
        self.assertEqual(_pair(result["cycling_eftp_watts"]), (275, INTERVALS))


class CurrentVo2AndRacePredictionTests(unittest.TestCase):
    def test_vo2max_cycling_garmin_then_ride_then_wellness_then_athlete(self) -> None:
        garmin = _garmin({"max_metrics": [{"cycling": {"vo2MaxValue": 61.0}}]})
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (61, GARMIN))

        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
        )
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (52, INTERVALS))

        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Ride"], "vo2_max": 51}],
                    )
                ]
            )
        )
        # Quirk: wellness-sourced VO2max carries the plain "Intervals.icu" label.
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (51, INTERVALS))

    def test_vo2max_running_uses_garmin_generic_then_intervals_running(self) -> None:
        # Quirk: a Garmin "generic" VO2max is reported as the running value.
        garmin = _garmin({"max_metrics": {"generic": {"vo2MaxValue": 51.0}}})
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (51, GARMIN))
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (52, INTERVALS))

        result = _current(
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "running_vo2max": 49}],
                    )
                ]
            )
        )
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (49, INTERVALS))

    def test_generic_athlete_vo2max_applies_to_both_sports_quirk(self) -> None:
        # Quirk: an athlete-level vo2max is used for cycling and for running.
        result = _current(_snapshot(athlete={"vo2max": 55}))
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (55, INTERVALS))
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (55, INTERVALS))
        self.assertEqual(result["cycling_vo2max_ml_kg_min"]["unit"], "ml/kg/min")

    def test_race_predictions_come_only_from_garmin(self) -> None:
        garmin = _garmin(
            {
                "race_predictions": {
                    "time5K": 1310,
                    "time10K": 2740,
                    "timeHalfMarathon": 6150,
                    "timeMarathon": 12600,
                }
            }
        )
        result = _current(garmin=garmin)
        self.assertEqual(_pair(result["run_5k_seconds"]), (1310, GARMIN))
        self.assertEqual(_pair(result["run_10k_seconds"]), (2740, GARMIN))
        self.assertEqual(_pair(result["run_half_marathon_seconds"]), (6150, GARMIN))
        self.assertEqual(_pair(result["run_marathon_seconds"]), (12600, GARMIN))

    def test_intervals_data_never_fills_race_prediction_slots(self) -> None:
        result = _current(
            _snapshot(
                athlete={
                    "run_5k_seconds": 1200,
                    "sport_settings": [_setting("Run", vo2max=50)],
                }
            )
        )
        for key in RACE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(_pair(result[key]), (None, None))
                self.assertEqual(result[key]["unit"], "s")


class CurrentResultShapeTests(unittest.TestCase):
    def test_result_keys_and_units_are_stable(self) -> None:
        result = _current()
        self.assertEqual(
            {key: metric["unit"] for key, metric in result.items()},
            {
                "weight_kg": "kg",
                "body_fat_pct": "%",
                "height_cm": "cm",
                "cycling_ftp_watts": "W",
                "run_threshold_watts": "W",
                "run_threshold_pace_seconds_per_km": "s/km",
                "run_zone2_pace_seconds_per_km": "s/km",
                "bike_threshold_hr_bpm": "bpm",
                "run_threshold_hr_bpm": "bpm",
                "cycling_eftp_watts": "W",
                "cycling_max_hr_bpm": "bpm",
                "running_max_hr_bpm": "bpm",
                "cycling_vo2max_ml_kg_min": "ml/kg/min",
                "running_vo2max_ml_kg_min": "ml/kg/min",
                "run_5k_seconds": "s",
                "run_10k_seconds": "s",
                "run_half_marathon_seconds": "s",
                "run_marathon_seconds": "s",
            },
        )
        for key, metric in result.items():
            with self.subTest(key=key):
                self.assertLessEqual({"value", "unit", "source", "note"}, set(metric))


if __name__ == "__main__":
    unittest.main()
