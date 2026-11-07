import copy
import unittest
from datetime import UTC, date, datetime

from performance_day_support import snapshot_metrics

from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL
from backend.providers.wahoo_threshold_mapping import (
    map_wahoo_power_zones,
    map_wahoo_user,
)


def empty_garmin(**overrides):
    keys = (
        "weight_kg",
        "cycling_ftp_watts",
        "run_threshold_watts",
        "run_threshold_pace_seconds_per_km",
        "bike_threshold_hr_bpm",
        "run_threshold_hr_bpm",
        "cycling_max_hr_bpm",
        "running_max_hr_bpm",
        "cycling_vo2max_ml_kg_min",
        "running_vo2max_ml_kg_min",
        "run_5k_seconds",
        "run_10k_seconds",
        "run_half_marathon_seconds",
        "run_marathon_seconds",
    )
    result = {
        key: {"value": None, "unit": "", "source": None, "note": ""} for key in keys
    }
    result.update(overrides)
    return result


class CurrentPerformanceMetricsTests(unittest.TestCase):
    def test_general_maximum_hr_is_garmins_and_ignores_the_intervals_setting(self):
        snapshot = {
            "athlete": {
                "sport_settings": [
                    {"types": ["Run"], "max_hr": 200},
                    {"types": ["Ride"], "max_hr": 190},
                ]
            }
        }
        for running, cycling, expected in (
            (187, None, 187),
            (None, 185, 185),
            (187, 185, 187),
            (None, None, None),
        ):
            with self.subTest(running=running, cycling=cycling):
                garmin = empty_garmin(
                    **{
                        key: {
                            "value": value,
                            "unit": "bpm",
                            "source_provider": "garmin",
                        }
                        for key, value in (
                            ("running_max_hr_bpm", running),
                            ("cycling_max_hr_bpm", cycling),
                        )
                    }
                )
                selected = snapshot_metrics(snapshot, {}, garmin)["max_hr_bpm"]
                self.assertEqual(selected["value"], expected)
                self.assertEqual(
                    selected["source_provider"], "garmin" if expected else None
                )

    def test_garmin_priority_and_metric_shape(self):
        garmin = empty_garmin(
            weight_kg={
                "value": 70,
                "unit": "kg",
                "source": "Garmin Connect",
                "note": "weight",
            },
            cycling_ftp_watts={
                "value": 302,
                "unit": "W",
                "source": "Garmin Connect",
                "note": "ftp",
            },
            cycling_max_hr_bpm={
                "value": 188,
                "unit": "bpm",
                "source": "Garmin Connect",
                "note": "",
            },
            cycling_vo2max_ml_kg_min={
                "value": 60,
                "unit": "ml/kg/min",
                "source": "Garmin Connect",
                "note": "",
            },
        )
        result = snapshot_metrics(
            {
                "athlete": {
                    "weight": 75,
                    "sport_settings": [
                        {"types": ["Ride"], "ftp": 250, "max_hr": 180, "vo2max": 50}
                    ],
                },
                "recent_wellness": [],
                "recent_activities": [],
            },
            {"weight_kg": 80},
            garmin,
        )
        # Garmin's dated measurement wins the recency rule (#1668); the undated
        # profile weight stays an alternative. The Intervals weight is no source.
        weight = dict(result["weight_kg"])
        alternatives = weight.pop("alternatives")
        self.assertTrue(weight.pop("conflict"))
        self.assertEqual(weight, garmin["weight_kg"])
        self.assertEqual([item["value"] for item in alternatives], [80])
        # Garmin's FTP and max HR are the values; the Intervals settings are not
        # alternatives.
        self.assertEqual(result["cycling_ftp_watts"], garmin["cycling_ftp_watts"])
        self.assertEqual(result["cycling_max_hr_bpm"], garmin["cycling_max_hr_bpm"])
        self.assertEqual(
            result["cycling_vo2max_ml_kg_min"], garmin["cycling_vo2max_ml_kg_min"]
        )

    def test_intervals_settings_give_no_current_value_but_the_profile_does(self):
        snapshot = {
            "athlete": {
                "weight": 78,
                "bodyFat": 18,
                "height": 1.8,
                "icu_ftp": 240,
                "sport_settings": [
                    {
                        "types": ["Rad"],
                        "ftp": 250,
                        "eftp": 260,
                        "lthr": 160,
                        "vo2max": 52,
                        "zone2_pace": 5.0,
                    },
                    {
                        "types": ["Laufen"],
                        "ftp": 280,
                        "lthr": 165,
                        "vo2max": 48,
                        "threshold_pace": 4.0,
                    },
                ],
            },
            "recent_wellness": [
                {
                    "id": "2026-08-31",
                    "weight": 79,
                    "bodyFat": 19,
                    "sport_info": [{"types": ["Ride"], "ftp": 256, "eFTP": 266}],
                },
            ],
            "recent_activities": [],
        }
        result = snapshot_metrics(
            snapshot,
            {"weight_kg": 80, "body_fat_pct": 20, "height_cm": 170},
            empty_garmin(),
            canonical=wahoo_canonical(),
        )
        self.assertEqual(result["weight_kg"]["value"], 80)
        self.assertEqual(result["weight_kg"]["source"], "Manuell")
        self.assertEqual(result["body_fat_pct"]["value"], 20)
        self.assertEqual(result["height_cm"]["value"], 170)
        for key in (
            "cycling_ftp_watts",
            "run_threshold_watts",
            "run_threshold_hr_bpm",
            "bike_threshold_hr_bpm",
            "run_threshold_pace_seconds_per_km",
            "cycling_vo2max_ml_kg_min",
            "running_vo2max_ml_kg_min",
        ):
            self.assertIsNone(result[key]["value"], key)
        self.assertNotIn("run_zone2_pace_seconds_per_km", result)

    def test_stored_eftp_is_not_a_current_metric(self):
        # Since #1727 the stored athlete, wellness and activity eFTP is not read.
        snapshot = {
            "athlete": {
                "sport_settings": [{"types": ["Ride"], "ftp": 300, "eftp": 309}]
            },
            "recent_wellness": [
                {"id": "2026-08-31", "sportInfo": [{"types": ["Ride"], "eftp": 266}]}
            ],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": "2026-09-01T07:00:00",
                    "icu_eftp": 290,
                }
            ],
        }
        result = snapshot_metrics(snapshot, {}, empty_garmin())
        self.assertIsNone(result["cycling_ftp_watts"]["value"])
        self.assertNotIn("cycling_eftp_watts", result)

    def test_intervals_summaries_are_no_max_hr_activity_fallback(self):
        # Canonical: the mapper classifies the Intervals.icu type, so the former raw
        # sport/activityName aliases ("Radfahren", "Laufen") and the maxHeartRate
        # key no longer reach the summaries; the type decides the sport.
        snapshot = {
            "athlete": {"sport_settings": [{"types": ["Ride"]}, {"types": ["Run"]}]},
            "recent_wellness": [],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": "2026-09-01T07:00:00",
                    "maxHR": 181,
                },
                {
                    "id": "run-1",
                    "type": "Run",
                    "start_date_local": "2026-09-02T07:00:00",
                    "maxHR": 191,
                },
                {
                    "id": "ride-2",
                    "type": "Ride",
                    "start_date_local": "2026-09-03T07:00:00",
                    "maxHR": 400,
                },
            ],
        }
        result = snapshot_metrics(snapshot, {}, empty_garmin())
        # #1686: Intervals.icu summaries no longer serve the activity fallback.
        self.assertIsNone(result["cycling_max_hr_bpm"]["value"])
        self.assertIsNone(result["running_max_hr_bpm"]["value"])
        self.assertIsNone(result["cycling_max_hr_bpm"]["source"])

    def test_thresholds_and_vo2max_come_from_garmin_only(self):
        snapshot = {
            "athlete": {
                "sport_settings": [
                    {"types": ["Ride"], "lthr": 160},
                    {
                        "types": ["Run"],
                        "threshold_pace": 4.0,
                        "zone2_pace": 5.0,
                        "lthr": 165,
                        "vo2max": 48,
                    },
                ]
            },
            "recent_wellness": [],
            "recent_activities": [],
        }
        garmin = empty_garmin(
            run_threshold_pace_seconds_per_km={
                "value": 240,
                "unit": "s/km",
                "source": "Garmin Connect",
                "source_provider": "garmin",
                "note": "",
            },
            running_vo2max_ml_kg_min={
                "value": 55,
                "unit": "ml/kg/min",
                "source": "Garmin Connect",
                "note": "",
            },
        )
        result = snapshot_metrics(snapshot, {}, garmin)
        self.assertIsNone(result["bike_threshold_hr_bpm"]["value"])
        self.assertIsNone(result["run_threshold_hr_bpm"]["value"])
        self.assertEqual(result["running_vo2max_ml_kg_min"]["value"], 55)
        self.assertIsNone(result["cycling_vo2max_ml_kg_min"]["value"])
        self.assertNotIn("run_zone2_pace_seconds_per_km", result)
        self.assertEqual(result["run_5k_seconds"]["value"], None)

    def test_invalid_values_and_inputs_are_not_mutated(self):
        snapshot = {
            "athlete": {
                "weight": "invalid",
                "height": "nan",
                "sport_settings": [{"types": ["Run"], "threshold_pace": 10000}],
            },
            "recent_wellness": [{"id": "2026-08-31", "bodyFat": "invalid"}],
            "recent_activities": [],
        }
        profile = {"weight_kg": 72, "body_fat_pct": 20, "height_cm": 175}
        garmin = empty_garmin()
        before = copy.deepcopy((snapshot, profile, garmin))
        result = snapshot_metrics(snapshot, profile, garmin)
        self.assertEqual(result["weight_kg"]["value"], 72)
        self.assertEqual(result["body_fat_pct"]["value"], 20)
        self.assertIsNone(result["run_threshold_pace_seconds_per_km"]["value"])
        self.assertEqual((snapshot, profile, garmin), before)


RETRIEVED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


def wahoo_canonical(*, ftp=None, weight=None):
    """Canonical inputs holding only Wahoo fallbacks, mapped by the real mapper."""
    wahoo_ftp = None
    if ftp is not None:
        zones = map_wahoo_power_zones(
            [
                {
                    "id": 1,
                    "workout_type_family_id": 0,  # biking family
                    "ftp": ftp,
                    "updated_at": "2026-10-01T10:00:00Z",
                }
            ],
            zone=UTC,
            retrieved_at=RETRIEVED,
        )
        wahoo_ftp = zones.records[0]
    wahoo_weight = None
    if weight is not None:
        profile = map_wahoo_user(
            {"weight": weight},
            observed_on=date(2026, 10, 12),
            retrieved_at=RETRIEVED,
        )
        wahoo_weight = profile.records[0]
    return CanonicalCurrentInputs(wahoo_ftp=wahoo_ftp, wahoo_weight=wahoo_weight)


def snapshot_with(athlete=None):
    return {
        "athlete": athlete or {},
        "recent_wellness": [],
        "recent_activities": [],
    }


class WahooFallbackPrecedenceTests(unittest.TestCase):
    def test_wahoo_ftp_is_used_when_garmin_has_none(self):
        result = snapshot_metrics(
            snapshot_with(), {}, empty_garmin(), canonical=wahoo_canonical(ftp=250)
        )

        ftp = result["cycling_ftp_watts"]
        self.assertEqual(250, ftp["value"])
        self.assertEqual(WAHOO_LABEL, ftp["source"])
        self.assertEqual("wahoo", ftp["source_provider"])

    def test_wahoo_ftp_beats_an_intervals_ftp(self):
        snapshot = snapshot_with({"sport_settings": [{"types": ["Ride"], "ftp": 240}]})

        result = snapshot_metrics(
            snapshot, {}, empty_garmin(), canonical=wahoo_canonical(ftp=300)
        )

        self.assertEqual(300, result["cycling_ftp_watts"]["value"])
        self.assertEqual("wahoo", result["cycling_ftp_watts"]["source_provider"])
        self.assertNotIn("alternatives", result["cycling_ftp_watts"])

    def test_garmin_ftp_beats_wahoo_ftp_and_intervals_is_ignored(self):
        garmin = empty_garmin(
            cycling_ftp_watts={
                "value": 302,
                "unit": "W",
                "source": "Garmin Connect",
                "note": "ftp",
            }
        )
        snapshot = snapshot_with({"sport_settings": [{"types": ["Ride"], "ftp": 240}]})

        result = snapshot_metrics(
            snapshot, {}, garmin, canonical=wahoo_canonical(ftp=300)
        )

        self.assertEqual(302, result["cycling_ftp_watts"]["value"])
        self.assertEqual(
            [300],
            [item["value"] for item in result["cycling_ftp_watts"]["alternatives"]],
        )
        without_wahoo = snapshot_metrics(snapshot, {}, garmin)
        self.assertEqual(302, without_wahoo["cycling_ftp_watts"]["value"])
        self.assertNotIn("alternatives", without_wahoo["cycling_ftp_watts"])

    def test_manual_profile_weight_beats_wahoo_weight(self):
        result = snapshot_metrics(
            snapshot_with(),
            {"weight_kg": 80},
            empty_garmin(),
            canonical=wahoo_canonical(weight=78.5),
        )

        self.assertEqual(80, result["weight_kg"]["value"])
        self.assertEqual("Manuell", result["weight_kg"]["source"])

    def test_wahoo_weight_is_used_when_nothing_else_is_stored(self):
        result = snapshot_metrics(
            snapshot_with(),
            {},
            empty_garmin(),
            canonical=wahoo_canonical(weight=78.5),
        )

        self.assertEqual(78.5, result["weight_kg"]["value"])
        self.assertEqual(WAHOO_LABEL, result["weight_kg"]["source"])
        self.assertEqual("wahoo", result["weight_kg"]["source_provider"])

    def test_an_intervals_weight_is_no_source(self):
        result = snapshot_metrics(
            snapshot_with({"weight": 77}),
            {},
            empty_garmin(),
            canonical=wahoo_canonical(weight=78.5),
        )

        self.assertEqual(78.5, result["weight_kg"]["value"])
        self.assertEqual("wahoo", result["weight_kg"]["source_provider"])


if __name__ == "__main__":
    unittest.main()
