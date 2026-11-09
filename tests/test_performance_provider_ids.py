"""Provider ids are additive on performance payloads; labels and values stay unchanged."""

import unittest
from datetime import date

from canonical_recovery_support import mapped_personal_recovery
from performance_day_support import (
    garmin_body_from_payload,
    garmin_metrics_from_payload,
    snapshot_metrics,
)

from backend.coach.context import coach_performance_projection
from backend.performance.body import body_history
from backend.performance.canonical_inputs import EMPTY_PERFORMANCE_INPUTS
from backend.performance.chart_history import analysis_history
from backend.performance.freshness import GarminSyncStatus

TODAY = date(2026, 10, 12)
CURRENT_KEYS = (
    "weight_kg",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
    "cycling_max_hr_bpm",
    "running_max_hr_bpm",
    "cycling_ftp_watts",
    "run_threshold_watts",
    "run_threshold_pace_seconds_per_km",
    "bike_threshold_hr_bpm",
    "run_threshold_hr_bpm",
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)


def _empty_garmin_metrics(**values):
    empty = {
        key: {
            "value": None,
            "unit": "",
            "source": None,
            "source_provider": None,
            "note": "",
        }
        for key in CURRENT_KEYS
    }
    for key, value in values.items():
        empty[key] = {
            "value": value,
            "unit": "W",
            "source": "Garmin Connect",
            "source_provider": "garmin",
            "note": "",
        }
    return empty


class ProviderIdPayloadTests(unittest.TestCase):
    def test_chart_history_series_carry_provider_ids_next_to_labels(self):
        result = analysis_history(
            GarminSyncStatus.from_state({}),
            TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )

        self.assertNotIn("cycling_eftp_watts", result["metrics"])
        ftp = result["metrics"]["cycling_ftp_watts"][0]
        self.assertEqual(ftp["source"], "Garmin Connect")
        self.assertEqual(ftp["source_provider"], "garmin")
        self.assertNotIn("cycling_eftp_watts", result["preferred_providers"])
        self.assertEqual(result["preferred_providers"]["cycling_ftp_watts"], "garmin")

    def test_body_history_series_and_policy_carry_provider_ids(self):
        garmin = {
            "weight": [{"date": "2026-10-10", "weightKg": 80, "bodyFat": 15}],
            "performance_history": [
                {"date": "2026-10-10", "metrics": {"cycling_ftp_watts": 250}}
            ],
        }
        result = body_history(
            GarminSyncStatus.from_state(garmin),
            TODAY,
            canonical=garmin_body_from_payload(garmin, TODAY),
            garmin_ftp=garmin_metrics_from_payload(garmin).performance_history[
                "cycling_ftp_watts"
            ],
        )
        metrics = result["windows"]["14d"]["metrics"]

        self.assertEqual(
            [item["source_provider"] for item in metrics["weight_kg"]], ["garmin"]
        )
        self.assertEqual(metrics["weight_kg"][0]["source"], "Garmin Connect")
        self.assertEqual(
            [item["source_provider"] for item in metrics["body_fat_pct"]], ["garmin"]
        )

        ftp_series = {
            item["source_provider"]: item for item in metrics["cycling_w_per_kg"]
        }
        self.assertEqual(ftp_series["garmin"]["source"], "Garmin Connect")
        self.assertEqual(ftp_series["garmin"]["power_method"], "FTP")
        self.assertNotIn("intervals", ftp_series)
        point = next(
            item
            for item in ftp_series["garmin"]["points"]
            if item["date"] == "2026-10-10"
        )
        self.assertEqual(point["value"], 3.125)
        self.assertEqual(point["weight_source"], "Garmin Connect")
        self.assertEqual(result["preferred_providers"]["weight_kg"], "garmin")

    def test_current_metrics_carry_provider_ids_and_manual_values_have_none(self):
        snapshot = {
            "athlete": {
                "sport_settings": [{"types": ["Ride"], "ftp": 240}],
                "weight": 79,
            },
            "recent_wellness": [],
            "recent_activities": [],
        }
        result = snapshot_metrics(
            snapshot,
            {"weight_kg": 81},
            _empty_garmin_metrics(cycling_ftp_watts=260),
        )

        # Garmin's FTP is the value; the Intervals ride setting is no source.
        self.assertEqual(result["cycling_ftp_watts"]["source"], "Garmin Connect")
        self.assertEqual(result["cycling_ftp_watts"]["source_provider"], "garmin")
        self.assertNotIn("alternatives", result["cycling_ftp_watts"])
        self.assertNotIn("cycling_eftp_watts", result)
        self.assertIsNone(result["run_threshold_watts"]["value"])
        self.assertIsNone(result["run_threshold_watts"]["source_provider"])
        # The profile weight is the only weight; the Intervals athlete weight is not.
        self.assertEqual(result["weight_kg"]["source"], "Manuell")
        self.assertIsNone(result["weight_kg"]["source_provider"])
        self.assertEqual(result["height_cm"]["source_provider"], None)

    def test_manual_profile_weight_has_no_provider_id(self):
        result = snapshot_metrics(
            {"recent_wellness": [], "recent_activities": []},
            {"weight_kg": 81},
            _empty_garmin_metrics(),
        )

        self.assertEqual(result["weight_kg"]["source"], "Manuell")
        self.assertIsNone(result["weight_kg"]["source_provider"])

    def test_recovery_baselines_carry_provider_ids_and_policy(self):
        result = mapped_personal_recovery(
            [{"id": "2026-10-10", "restingHR": 50, "hrv": 60, "sleepSecs": 25200}],
            {},
            {"sleep_target_hours": 8},
            TODAY,
        )

        for baseline in result["baselines"]:
            self.assertEqual(baseline["source"], "Garmin Connect")
            self.assertEqual(baseline["source_provider"], "garmin")
        self.assertEqual(result["preferred_providers"]["hrv"], "garmin")
        self.assertEqual(result["sleep_deficits"][0]["source"], "Garmin Connect")

    def test_coach_projection_keeps_recovery_contract_with_additive_provider_ids(self):
        # backend/coach/context.py is unchanged (owned by U10); the projection
        # passes the additive provider-id keys through without altering the
        # existing baseline contract.
        recovery = mapped_personal_recovery(
            [{"id": "2026-10-10", "restingHR": 50}], {}, {}, TODAY
        )

        projected = coach_performance_projection({"personal_recovery": recovery})[
            "personal_recovery"
        ]

        self.assertEqual(projected["baselines"][0]["source"], "Garmin Connect")
        self.assertEqual(projected["baselines"][0]["source_provider"], "garmin")
        self.assertIn("preferred_providers", projected)
        self.assertNotIn("history", projected["baselines"][0])


if __name__ == "__main__":
    unittest.main()
