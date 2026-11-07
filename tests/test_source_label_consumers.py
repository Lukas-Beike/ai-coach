"""Legacy readers keep their source labels after taking them from the label table."""

from __future__ import annotations

import unittest
from datetime import date

from backend.activities.duplicates import duplicate_delete_action
from backend.performance import (
    body,
    current_metrics,
    daily_health,
    garmin_metrics,
)
from backend.performance.season_inputs import SeasonLoadInputs
from backend.planning import season_preparation
from backend.sync import garmin_weight

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

    def test_season_preparation_basis_names_the_local_curve(self):
        # Since #1726 the basis is yesterday's local fitness (M7), never
        # Intervals.icu recorded wellness.
        inputs = SeasonLoadInputs(
            basis_day=date(2026, 10, 1), ctl=50.0, atl=60.0, completed_today=()
        )
        result = season_preparation.load_scenarios(
            None, {}, date(2026, 10, 2), SEASON_VALUES, inputs=inputs
        )
        self.assertEqual("Lokal berechnet (M7)", result["basis"]["source"])
