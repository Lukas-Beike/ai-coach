import copy
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from performance_day_support import snapshot_metrics

from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.performance.current_metrics import (
    PROVIDER_INTERVALS_NAME,
)
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)
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
    def test_general_maximum_hr_prefers_garmin_before_comparing_sports(self):
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
            (None, None, 200),
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
                    selected["source_provider"],
                    "garmin" if running or cycling else "intervals",
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
        self.assertEqual(result["weight_kg"], garmin["weight_kg"])
        self.assertEqual(result["cycling_ftp_watts"], garmin["cycling_ftp_watts"])
        self.assertEqual(result["cycling_max_hr_bpm"], garmin["cycling_max_hr_bpm"])
        self.assertEqual(
            result["cycling_vo2max_ml_kg_min"], garmin["cycling_vo2max_ml_kg_min"]
        )

    def test_intervals_wellness_athlete_profile_fallbacks_and_eftp(self):
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
                    "id": "2026-08-30",
                    "sportInfo": [{"types": ["Ride"], "ftp": 255, "eFTP": 265}],
                },
                {
                    "id": "2026-08-31",
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 256, "eFTP": 266},
                        {"types": ["Run"], "lthr": 166},
                    ],
                },
            ],
            "recent_activities": [
                {"type": "Ride", "start_date_local": "2026-08-30", "icu_eftp": 270},
                {"type": "Ride", "start_date_local": "2026-08-31", "icu_eftp": 275},
            ],
        }
        result = snapshot_metrics(
            snapshot,
            {"weight_kg": 80, "body_fat_pct": 20, "height_cm": 170},
            empty_garmin(),
            canonical=eftp_canonical(athlete=260, wellness=266),
        )
        self.assertEqual(result["weight_kg"]["value"], 78)
        self.assertEqual(result["body_fat_pct"]["value"], 18)
        self.assertEqual(result["height_cm"]["value"], 180)
        self.assertEqual(result["cycling_ftp_watts"]["value"], 250)
        self.assertEqual(result["cycling_eftp_watts"]["value"], 260)
        self.assertEqual(
            result["cycling_eftp_watts"]["source"], PROVIDER_INTERVALS_NAME
        )
        self.assertEqual(result["run_threshold_watts"]["value"], 280)
        self.assertEqual(result["run_threshold_hr_bpm"]["value"], 165)
        # The mapped setting eFTP of this sync is the canonical athlete eFTP.
        result = snapshot_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["cycling_eftp_watts"]["value"], 260)

    def test_eftp_follows_the_canonical_chain_then_the_latest_ride_activity(self):
        snapshot = {
            "athlete": {"sport_settings": [{"types": ["Ride"], "ftp": 300}]},
            "recent_wellness": [{"id": "2026-08-31"}],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": "2026-09-01T07:00:00",
                    "icu_eftp": 290,
                }
            ],
        }
        chain = {
            "athlete": eftp_canonical(athlete=309, wellness=266),
            "wellness": eftp_canonical(wellness=266),
            "activity": eftp_canonical(),
        }
        expected = {"athlete": 309, "wellness": 266, "activity": 290}
        for name, canonical in chain.items():
            with self.subTest(name):
                result = snapshot_metrics(
                    snapshot, {}, empty_garmin(), canonical=canonical
                )
                self.assertEqual(result["cycling_ftp_watts"]["value"], 300)
                self.assertEqual(result["cycling_eftp_watts"]["value"], expected[name])
        snapshot["recent_activities"] = []
        result = snapshot_metrics(snapshot, {}, empty_garmin())
        self.assertIsNone(result["cycling_eftp_watts"]["value"])

    def test_max_hr_activity_fallback_by_canonical_sport(self):
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
        self.assertEqual(result["cycling_max_hr_bpm"]["value"], 181)
        self.assertEqual(result["running_max_hr_bpm"]["value"], 191)
        self.assertEqual(result["cycling_max_hr_bpm"]["source"], "Intervals.icu")

    def test_threshold_zone2_and_prediction_metrics(self):
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
        result = snapshot_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["run_threshold_pace_seconds_per_km"]["value"], 250)
        self.assertEqual(result["run_zone2_pace_seconds_per_km"]["value"], 200)
        self.assertEqual(result["bike_threshold_hr_bpm"]["value"], 160)
        self.assertEqual(result["running_vo2max_ml_kg_min"]["value"], 48)
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
        self.assertEqual(result["run_threshold_pace_seconds_per_km"]["value"], 10000)
        self.assertEqual((snapshot, profile, garmin), before)


RETRIEVED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


def eftp_canonical(*, athlete=None, wellness=None):
    """Canonical inputs holding ride eFTP observations, mapped by the real mappers."""
    athlete_eftp = None
    if athlete is not None:
        thresholds = map_intervals_athlete_thresholds(
            {
                "id": "athlete-1",
                "sportSettings": [{"types": ["Ride"], "eftp": athlete}],
            },
            observed_on=date(2026, 10, 12),
            retrieved_at=RETRIEVED,
        )
        athlete_eftp = next(r for r in thresholds.records if r.kind is MetricKind.EFTP)
    wellness_eftp = None
    if wellness is not None:
        rows = map_intervals_wellness(
            [
                {
                    "id": "2026-10-11",
                    "sportInfo": [{"types": ["Ride"], "eftp": wellness}],
                }
            ],
            retrieved_at=RETRIEVED,
        )
        wellness_eftp = next(r for r in rows.records if r.kind is MetricKind.EFTP)
    return replace(
        wahoo_canonical(), athlete_eftp=athlete_eftp, wellness_eftp=wellness_eftp
    )


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
    return CanonicalCurrentInputs(
        bike_threshold_hr=(),
        run_threshold_hr=(),
        athlete_threshold_hr=None,
        cycling_vo2max=(),
        running_vo2max=(),
        wellness_weight=None,
        athlete_weight=None,
        wahoo_ftp=wahoo_ftp,
        wahoo_weight=wahoo_weight,
    )


def snapshot_with(athlete=None):
    return {
        "athlete": athlete or {},
        "recent_wellness": [],
        "recent_activities": [],
    }


class WahooFallbackPrecedenceTests(unittest.TestCase):
    def test_wahoo_ftp_fills_in_only_when_intervals_has_no_ftp(self):
        result = snapshot_metrics(
            snapshot_with(), {}, empty_garmin(), canonical=wahoo_canonical(ftp=250)
        )

        ftp = result["cycling_ftp_watts"]
        self.assertEqual(250, ftp["value"])
        self.assertEqual(WAHOO_LABEL, ftp["source"])
        self.assertEqual("wahoo", ftp["source_provider"])

    def test_intervals_ftp_beats_wahoo_ftp(self):
        snapshot = snapshot_with({"sport_settings": [{"types": ["Ride"], "ftp": 240}]})

        result = snapshot_metrics(
            snapshot, {}, empty_garmin(), canonical=wahoo_canonical(ftp=300)
        )

        self.assertEqual(240, result["cycling_ftp_watts"]["value"])
        self.assertEqual(PROVIDER_INTERVALS_NAME, result["cycling_ftp_watts"]["source"])

    def test_garmin_ftp_beats_intervals_and_wahoo_ftp(self):
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

    def test_intervals_weight_beats_wahoo_weight(self):
        result = snapshot_metrics(
            snapshot_with({"weight": 77}),
            {},
            empty_garmin(),
            canonical=wahoo_canonical(weight=78.5),
        )

        self.assertEqual(77, result["weight_kg"]["value"])
        self.assertEqual(PROVIDER_INTERVALS_NAME, result["weight_kg"]["source"])


if __name__ == "__main__":
    unittest.main()
