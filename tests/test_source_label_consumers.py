"""Legacy readers keep their source labels after taking them from the label table."""

from __future__ import annotations

import unittest

from backend.performance import (
    body,
    current_metrics,
    daily_health,
    garmin_metrics,
)
from backend.planning import season_preparation
from backend.sync import garmin_weight


class ExportedSourceConstantTests(unittest.TestCase):
    def test_daily_health_garmin_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", daily_health.GARMIN_PERFORMANCE_SOURCE)

    def test_season_preparation_activity_source_is_unchanged(self):
        self.assertEqual(
            "Garmin Connect, Wahoo recorded activities",
            season_preparation.ACTIVITY_SOURCE,
        )

    def test_current_metrics_source_constants_are_unchanged(self):
        self.assertEqual("Intervals.icu", current_metrics.PROVIDER_INTERVALS_NAME)
        self.assertEqual("Garmin Connect", current_metrics.GARMIN_PERFORMANCE_SOURCE)

    def test_garmin_performance_note_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", garmin_metrics.GARMIN_PERFORMANCE_SOURCE)

    def test_garmin_weight_body_history_source_is_unchanged(self):
        self.assertEqual("Garmin Connect", garmin_weight.GARMIN_PERFORMANCE_SOURCE)

    def test_body_history_source_constants_are_unchanged(self):
        self.assertEqual("Garmin Connect", body.GARMIN_SOURCE)
