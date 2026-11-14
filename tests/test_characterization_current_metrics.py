"""Characterize current source precedence of ``current_performance_metrics``.

Each synthetic snapshot runs through the Intervals.icu mappers and the canonical
current read. Intervals.icu is never a source of a current value (athlete decision
2026-11-07), so its athlete settings, sport settings and wellness rows give no
value; the tests pin that, and the Garmin, Wahoo and profile precedence beside it.
Quirks are marked with a "Quirk:" comment and intended differences with
"Canonical:". Note text is not asserted because it is not part of the precedence
contract.
"""

import unittest
from datetime import UTC, date, datetime
from typing import Any

from performance_day_support import snapshot_metrics

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.sync.garmin_performance_history import current_garmin_metrics

TODAY = date(2026, 5, 4)
GARMIN = "Garmin Connect"
INTERVALS = "Intervals.icu"
PROFILE = "Manuell"

RACE_KEYS = (
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)
INTERVALS_ONLY_KEYS = (
    "cycling_ftp_watts",
    "run_threshold_watts",
    "run_threshold_pace_seconds_per_km",
    "bike_threshold_hr_bpm",
    "run_threshold_hr_bpm",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
)


def _garmin(raw: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return current_garmin_metrics(raw or {}, TODAY)


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
    return snapshot_metrics(
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


def _garmin_body(kind: MetricKind, value: float, day: str) -> Observation:
    """A Garmin device measurement as the canonical Garmin read returns it."""
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=date.fromisoformat(day),
        observed_at=None,
        provenance=Provenance(
            provider=ProviderId.GARMIN,
            source_kind=SourceKind.DEVICE_MEASURED,
            source_record_id=f"weight[0]:{day}",
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
            label=None,
        ),
    )


class BodyRecencyTests(unittest.TestCase):
    """Weight and body fat take the most recent Garmin, profile or Wahoo value."""

    def _body(self, garmin_body: tuple[Observation, ...]) -> dict[str, Any]:
        snapshot = _snapshot(
            wellness=[_wellness("2026-05-03", weight=70.0, bodyFat=15.0)]
        )
        return snapshot_metrics(snapshot, {}, _garmin(), garmin_body=garmin_body)

    def test_a_newer_intervals_measurement_does_not_beat_an_older_garmin_one(
        self,
    ) -> None:
        result = self._body((_garmin_body(MetricKind.WEIGHT, 72.0, "2026-04-30"),))

        weight = result["weight_kg"]
        self.assertEqual((weight["value"], weight["source_provider"]), (72, "garmin"))
        self.assertNotIn("alternatives", weight)

    def test_a_garmin_device_measurement_wins_within_one_day(self) -> None:
        result = self._body(
            (
                _garmin_body(MetricKind.WEIGHT, 70.5, "2026-05-02"),
                _garmin_body(MetricKind.BODY_FAT, 16.0, "2026-05-03"),
            )
        )

        self.assertEqual(result["weight_kg"]["value"], 70.5)
        self.assertEqual(result["weight_kg"]["source_provider"], "garmin")
        self.assertNotIn("alternatives", result["weight_kg"])
        self.assertEqual(result["body_fat_pct"]["value"], 16)
        self.assertEqual(result["body_fat_pct"]["source_provider"], "garmin")
        self.assertNotIn("alternatives", result["body_fat_pct"])

    def test_the_intervals_rows_alone_give_neither_weight_nor_body_fat(self) -> None:
        result = self._body(())

        self.assertEqual(_pair(result["weight_kg"]), (None, None))
        self.assertEqual(_pair(result["body_fat_pct"]), (None, None))


class CurrentWeightChainTests(unittest.TestCase):
    def test_garmin_weight_wins_over_the_profile_and_ignores_intervals(self) -> None:
        garmin = _garmin({"weight": _garmin_weight("2026-05-03", 72800)})
        result = _current(
            _snapshot(
                athlete={"weight": 80},
                wellness=[_wellness("2026-05-03", weight=79)],
            ),
            {"weight_kg": 81},
            garmin,
        )
        weight = dict(result["weight_kg"])
        alternatives = weight.pop("alternatives")
        self.assertTrue(weight.pop("conflict"))
        self.assertEqual(weight, garmin["weight_kg"])
        self.assertEqual(_pair(result["weight_kg"]), (72.8, GARMIN))
        self.assertEqual(result["weight_kg"]["unit"], "kg")
        self.assertEqual([item["value"] for item in alternatives], [81])

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
        # so a 2026-04-01 Garmin weight beats the 2026-05-03 wellness weight; the
        # wellness weight is no source at all.
        garmin = _garmin({"weight": _garmin_weight("2026-04-01", 71500)})
        result = _current(
            _snapshot(wellness=[_wellness("2026-05-03", weight=78)]),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["weight_kg"]), (71.5, GARMIN))
        self.assertNotIn("alternatives", result["weight_kg"])

    def test_weight_is_the_profile_value_without_garmin(self) -> None:
        cases = (
            (
                "wellness",
                _snapshot(
                    athlete={"weight": 80},
                    wellness=[_wellness("2026-05-03", weight=78)],
                ),
            ),
            ("athlete", _snapshot(athlete={"weight": 80})),
            ("profile", _snapshot()),
        )
        for name, snapshot in cases:
            with self.subTest(source=name):
                result = _current(snapshot, {"weight_kg": 81})
                self.assertEqual(_pair(result["weight_kg"]), (81, PROFILE))
                self.assertNotIn("alternatives", result["weight_kg"])

    def test_weight_is_empty_without_any_source(self) -> None:
        result = _current()
        self.assertEqual(_pair(result["weight_kg"]), (None, None))
        self.assertEqual(result["weight_kg"]["unit"], "kg")

    def test_intervals_weight_alone_is_empty_in_every_form(self) -> None:
        for name, snapshot in (
            (
                "comma decimal",
                _snapshot(
                    athlete={"weight": 79},
                    wellness=[_wellness("2026-05-03", weight="78,5")],
                ),
            ),
            (
                "latest row of several",
                _snapshot(
                    wellness=[
                        _wellness("2026-05-01", weight=80),
                        _wellness("2026-05-03", weight=78),
                        _wellness("2026-05-02", weight=79),
                    ]
                ),
            ),
            ("unpadded id", _snapshot(wellness=[_wellness("2026-5-9", weight=77)])),
            ("zero", _snapshot(wellness=[_wellness("2026-05-03", weight=0)])),
        ):
            with self.subTest(name):
                self.assertEqual(_pair(_current(snapshot)["weight_kg"]), (None, None))


class CurrentBodyMetricTests(unittest.TestCase):
    def test_body_fat_ignores_garmin_weight_payload_body_fat(self) -> None:
        garmin = _garmin({"weight": _garmin_weight("2026-05-03", 72800)})
        result = _current(garmin=garmin)
        self.assertEqual(_pair(result["body_fat_pct"]), (None, None))

    def test_body_fat_is_the_profile_value_and_ignores_intervals(self) -> None:
        cases = (
            (
                "wellness bodyFat",
                _snapshot(wellness=[_wellness("2026-05-03", bodyFat=17)]),
            ),
            (
                "wellness body_fat",
                _snapshot(wellness=[_wellness("2026-05-03", body_fat=16)]),
            ),
            ("athlete bodyFat", _snapshot(athlete={"bodyFat": 18})),
            ("athlete body_fat", _snapshot(athlete={"body_fat": 19})),
            ("profile", _snapshot()),
        )
        for name, snapshot in cases:
            with self.subTest(source=name):
                result = _current(snapshot, {"body_fat_pct": 20})
                self.assertEqual(_pair(result["body_fat_pct"]), (20, PROFILE))
                self.assertNotIn("alternatives", result["body_fat_pct"])
                self.assertEqual(result["body_fat_pct"]["unit"], "%")

    def test_body_fat_from_intervals_alone_is_empty(self) -> None:
        result = _current(
            _snapshot(wellness=[_wellness("2026-05-03", bodyFat="18.426")])
        )
        self.assertEqual(_pair(result["body_fat_pct"]), (None, None))
        self.assertEqual(result["body_fat_pct"]["unit"], "%")

    def test_intervals_height_is_no_source(self) -> None:
        for raw in (1.2, 1.8, 2.5, "1,75", 180, 1.19, 2.51):
            with self.subTest(raw=raw):
                result = _current(_snapshot(athlete={"height": raw}))
                self.assertEqual(_pair(result["height_cm"]), (None, None))
                self.assertEqual(result["height_cm"]["unit"], "cm")

    def test_profile_height_is_the_only_height(self) -> None:
        result = _current(
            _snapshot(athlete={"height_cm": 170, "height": 1.8}), {"height_cm": 175}
        )
        self.assertEqual(_pair(result["height_cm"]), (175, PROFILE))

    def test_profile_height_in_metres_is_converted_quirk(self) -> None:
        # Quirk: the metre-to-cm conversion is applied to the local profile.
        result = _current(_snapshot(), {"height_cm": 1.75})
        self.assertEqual(_pair(result["height_cm"]), (175, PROFILE))

        result = _current()
        self.assertEqual(_pair(result["height_cm"]), (None, None))


class CurrentThresholdTests(unittest.TestCase):
    def test_cycling_ftp_is_garmins_and_the_intervals_setting_is_ignored(self) -> None:
        # Canonical (2026-11-07): Intervals.icu is never a source, so Garmin's
        # auto-detected FTP is the value and no alternative is listed.
        garmin = _garmin({"cycling_ftp": {"functionalThresholdPower": 302}})
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", ftp=250)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["cycling_ftp_watts"]), (302, GARMIN))
        self.assertNotIn("alternatives", result["cycling_ftp_watts"])
        self.assertEqual(
            _pair(_current(garmin=garmin)["cycling_ftp_watts"]), (302, GARMIN)
        )

        for invalid in (49, 701):
            with self.subTest(invalid=invalid):
                result = _current(
                    _snapshot(athlete={"sport_settings": [_setting("Ride", ftp=250)]}),
                    garmin=_garmin(
                        {"cycling_ftp": {"functionalThresholdPower": invalid}}
                    ),
                )
                self.assertEqual(_pair(result["cycling_ftp_watts"]), (None, None))

    def test_intervals_ftp_in_every_form_gives_no_cycling_ftp(self) -> None:
        for name, snapshot in (
            (
                "ride setting",
                _snapshot(athlete={"sport_settings": [_setting("Ride", ftp=250)]}),
            ),
            (
                "indoor ftp",
                _snapshot(
                    athlete={
                        "sport_settings": [_setting("Ride", ftp=250, indoor_ftp=240)]
                    }
                ),
            ),
            ("athlete icu_ftp", _snapshot(athlete={"icu_ftp": 240})),
            (
                "wellness sport info",
                _snapshot(
                    wellness=[
                        _wellness(
                            "2026-05-03", sport_info=[{"types": ["Ride"], "ftp": 255}]
                        )
                    ]
                ),
            ),
            (
                "first setting without value",
                _snapshot(
                    athlete={
                        "icu_ftp": 240,
                        "sport_settings": [_setting("Ride"), _setting("Rad", ftp=300)],
                    }
                ),
            ),
        ):
            with self.subTest(name):
                self.assertEqual(
                    _pair(_current(snapshot)["cycling_ftp_watts"]), (None, None)
                )

    def test_run_threshold_watts_is_garmins_only(self) -> None:
        result = _current(
            _snapshot(
                athlete={"icu_ftp": 240, "sport_settings": [_setting("Run", ftp=280)]}
            )
        )
        self.assertEqual(_pair(result["run_threshold_watts"]), (None, None))

        garmin = _garmin(
            {"running_threshold": {"power": {"functionalThresholdPower": 328}}}
        )
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Run", ftp=280)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["run_threshold_watts"]), (328, GARMIN))

    def test_run_threshold_pace_is_garmins_only(self) -> None:
        for raw in (4.0, 3.5, 250, 20, -4.0, "4:27"):
            with self.subTest(raw=raw):
                result = _current(
                    _snapshot(
                        athlete={
                            "sport_settings": [_setting("Run", threshold_pace=raw)]
                        }
                    )
                )
                self.assertEqual(
                    _pair(result["run_threshold_pace_seconds_per_km"]), (None, None)
                )

        garmin = _garmin(
            {"running_threshold": {"speed_and_heart_rate": {"speed": 4.0}}}
        )
        result = _current(
            _snapshot(
                athlete={"sport_settings": [_setting("Run", threshold_pace=3.5)]}
            ),
            garmin=garmin,
        )
        self.assertEqual(
            _pair(result["run_threshold_pace_seconds_per_km"]), (250, GARMIN)
        )

    def test_the_intervals_zone2_pace_is_no_current_metric(self) -> None:
        for key in ("zone2_pace", "zone_2_pace", "z2_pace", "pace_zone2", "zone2Pace"):
            with self.subTest(key=key):
                result = _current(
                    _snapshot(
                        athlete={"sport_settings": [_setting("Run", **{key: 5.0})]}
                    )
                )
                self.assertNotIn("run_zone2_pace_seconds_per_km", result)

    def test_threshold_hr_is_garmins_only(self) -> None:
        athlete = {"lthr": 165, "sport_settings": [_setting("Run", lthr=170)]}
        for snapshot in (
            _snapshot(athlete=athlete),
            _snapshot(athlete={"lthr": 165}),
            _snapshot(
                athlete={"sport_settings": [_setting("Ride", lthr=160)]},
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Run"], "lthr": 166}],
                    )
                ],
            ),
            _snapshot(),
        ):
            result = _current(snapshot)
            self.assertEqual(_pair(result["bike_threshold_hr_bpm"]), (None, None))
            self.assertEqual(_pair(result["run_threshold_hr_bpm"]), (None, None))

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
    def test_sport_setting_max_hr_is_no_source(self) -> None:
        for key in ("max_hr", "maxHR", "maxHeartRate", "max_heartrate"):
            with self.subTest(key=key):
                result = _current(
                    _snapshot(
                        athlete={"sport_settings": [_setting("Ride", **{key: 190})]}
                    )
                )
                self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (None, None))

    def test_out_of_range_setting_does_not_read_wellness_sport_info(self) -> None:
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
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (None, None))

    def test_activity_maximum_is_the_last_resort_and_the_athlete_max_hr_is_ignored(
        self,
    ) -> None:
        activities = [
            {
                "id": "ride-1",
                "type": "Ride",
                "start_date_local": "2026-05-01T07:00:00",
                "maxHR": 181,
            },
            {
                "id": "ride-2",
                "type": "Ride",
                "start_date_local": "2026-05-02T07:00:00",
                "maxHR": 195,
            },
            {
                "id": "ride-3",
                "type": "Ride",
                "start_date_local": "2026-05-03T07:00:00",
                "maxHR": 400,
            },
            {
                "id": "run-1",
                "type": "Run",
                "start_date_local": "2026-05-03T08:00:00",
                "maxHR": 210,
            },
        ]
        # The activity maximum is the activity's own recorded value, labelled by
        # the provider whose summary reports it; the athlete's max HR is no source.
        result = _current(
            _snapshot(athlete={"max_hr": 200}, activities=activities),
        )
        # Neither the Intervals.icu athlete max HR nor its activity summaries
        # (#1686) serve the value any more.
        self.assertIsNone(result["cycling_max_hr_bpm"]["value"])
        self.assertIsNone(result["running_max_hr_bpm"]["value"])

        result = _current(_snapshot(athlete={"max_hr": 186}))
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (None, None))

    def test_athlete_max_hr_outside_range_is_ignored(self) -> None:
        result = _current(_snapshot(athlete={"max_hr": 300}))
        self.assertEqual(_pair(result["cycling_max_hr_bpm"]), (None, None))
        self.assertEqual(_pair(result["running_max_hr_bpm"]), (None, None))

    def test_garmin_profile_max_hr_is_the_value(self) -> None:
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
        self.assertNotIn("alternatives", result["cycling_max_hr_bpm"])


class CurrentEftpTests(unittest.TestCase):
    def test_stored_eftp_is_no_current_metric(self) -> None:
        # Since #1727 no Intervals.icu eFTP is read: not the athlete setting, the
        # wellness sportInfo or the latest ride activity.
        snapshot = _snapshot(
            athlete={"sport_settings": [_setting("Ride", eftp=262)]},
            wellness=[
                _wellness("2026-05-03", sportInfo=[{"types": ["Ride"], "eftp": 265}])
            ],
            activities=[
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": "2026-05-03T07:00:00",
                    "icu_eftp": 270,
                }
            ],
        )
        self.assertNotIn("cycling_eftp_watts", _current(snapshot))


class CurrentVo2AndRacePredictionTests(unittest.TestCase):
    def test_vo2max_cycling_is_garmins_only(self) -> None:
        garmin = _garmin(
            {
                "max_metrics": [
                    {"cycling": {"calendarDate": "2026-05-04", "vo2MaxValue": 61.0}}
                ]
            }
        )
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (61, GARMIN))

        for snapshot in (
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
            _snapshot(
                wellness=[
                    _wellness(
                        "2026-05-03",
                        sport_info=[{"types": ["Ride"], "vo2_max": 51}],
                    )
                ]
            ),
        ):
            result = _current(snapshot)
            self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (None, None))

    def test_vo2max_running_uses_garmin_generic_only(self) -> None:
        # Quirk: a Garmin "generic" VO2max is reported as the running value.
        garmin = _garmin(
            {
                "max_metrics": {
                    "generic": {"calendarDate": "2026-05-04", "vo2MaxValue": 51.0}
                }
            }
        )
        result = _current(
            _snapshot(athlete={"sport_settings": [_setting("Ride", vo2max=52)]}),
            garmin=garmin,
        )
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (51, GARMIN))
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (None, None))

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
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (None, None))

    def test_generic_athlete_vo2max_applies_to_neither_sport(self) -> None:
        result = _current(_snapshot(athlete={"vo2max": 55}))
        self.assertEqual(_pair(result["cycling_vo2max_ml_kg_min"]), (None, None))
        self.assertEqual(_pair(result["running_vo2max_ml_kg_min"]), (None, None))
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
                "bike_threshold_hr_bpm": "bpm",
                "run_threshold_hr_bpm": "bpm",
                "cycling_max_hr_bpm": "bpm",
                "running_max_hr_bpm": "bpm",
                "max_hr_bpm": "bpm",
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

    def test_intervals_settings_give_no_value_for_any_threshold_metric(self) -> None:
        result = _current(
            _snapshot(
                athlete={
                    "icu_ftp": 240,
                    "lthr": 165,
                    "max_hr": 190,
                    "vo2max": 55,
                    "weight": 80,
                    "sport_settings": [
                        _setting("Ride", ftp=250, lthr=160, vo2max=52, max_hr=190),
                        _setting("Run", ftp=280, lthr=170, threshold_pace=4.0),
                    ],
                }
            )
        )
        for key in INTERVALS_ONLY_KEYS:
            with self.subTest(key=key):
                self.assertIsNone(result[key]["value"])
                self.assertIsNone(result[key]["source"])


if __name__ == "__main__":
    unittest.main()
