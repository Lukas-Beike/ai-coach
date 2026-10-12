"""Legacy readers keep their source labels after taking them from the label table."""

from __future__ import annotations

import unittest
from datetime import date

from backend.activities.duplicates import duplicate_delete_action
from backend.performance import (
    activity_read_service,
    body,
    current_metrics,
    daily_health,
    garmin_metrics,
    garmin_weight,
)
from backend.planning import season_preparation

SEASON_VALUES = {"end": "2026-10-04", "load_scale": 0.8, "taper_days": 2}


class ExportedSourceConstantTests(unittest.TestCase):
    def test_daily_health_garmin_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", daily_health.GARMIN_PERFORMANCE_SOURCE)

    def test_season_preparation_activity_source_is_unchanged(self):
        self.assertEqual(
            "Intervals.icu recorded activities", season_preparation.ACTIVITY_SOURCE
        )

    def test_current_metrics_source_constants_are_unchanged(self):
        self.assertEqual("Intervals.icu", current_metrics.PROVIDER_INTERVALS_NAME)
        self.assertEqual(
            "Intervals.icu Wellness", current_metrics.PROVIDER_INTERVALS_WELLNESS_NAME
        )
        self.assertEqual("Garmin Connect", current_metrics.GARMIN_PERFORMANCE_SOURCE)

    def test_garmin_performance_note_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", garmin_metrics.GARMIN_PERFORMANCE_SOURCE)

    def test_garmin_weight_body_history_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", garmin_weight.GARMIN_PERFORMANCE_SOURCE)

    def test_body_history_source_constants_are_unchanged(self):
        self.assertEqual("Intervals.icu Wellness", body.INTERVALS_SOURCE)
        self.assertEqual("Garmin Connect", body.GARMIN_SOURCE)


class EmittedSourceOutputTests(unittest.TestCase):
    def test_duplicate_confirmation_payload_names_garmin_source(self):
        pair = {
            "canonical_id": "wahoo-1",
            "canonical_name": "Wahoo ride",
            "duplicate_id": "garmin-1",
            "duplicate_name": "Garmin ride",
            "start_date_local": "2026-09-20T07:12:00",
            "snapshot_synced_at": "2026-09-20T08:00:00Z",
        }
        diff = duplicate_delete_action(pair)["diff"][0]
        self.assertEqual("Garmin", diff["source"])
        self.assertEqual("Wahoo", diff["kept_source"])

    def test_activity_detail_metadata_names_intervals_source(self):
        metadata = activity_read_service._detail_metadata(None, False, {})
        self.assertEqual("Intervals.icu", metadata["source"])

    def test_season_preparation_wellness_basis_names_recorded_wellness(self):
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        result = season_preparation.load_scenarios(
            snapshot, {}, date(2026, 10, 2), SEASON_VALUES
        )
        self.assertEqual("Intervals.icu recorded wellness", result["basis"]["source"])
