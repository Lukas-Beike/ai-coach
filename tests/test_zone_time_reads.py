"""Report zone times count in one zone model per sum (#1743)."""

from __future__ import annotations

import unittest

from backend.performance.progress_report import intensity_3zone
from backend.performance.training_report import zone_distribution
from backend.performance.zone_time_reads import with_zone_times


def _zones(seconds: dict[str, float]) -> list[dict[str, float | str]]:
    return [{"id": zone, "secs": value} for zone, value in seconds.items()]


LOCAL = {
    "label": "Zoneneinstellungen",
    "heart_rate": _zones({"Z1": 600.0, "Z2": 1200.0}),
    "pace": _zones({"Z1": 300.0, "Z4": 900.0}),
}


def _summaries() -> tuple[dict, ...]:
    """A run with stored local zone times and one with Garmin watch zones only."""
    return with_zone_times(
        [
            {
                "id": "act_local",
                "sport": "run",
                "moving_duration_s": 1800,
                # The watch zones of a session with local zone times are replaced.
                "heart_rate_zone_times": _zones({"Z1": 1800.0}),
                "sources": {"heart_rate_zone_times": "Garmin Connect"},
            },
            {
                "id": "act_watch",
                "sport": "run",
                "moving_duration_s": 1200,
                "heart_rate_zone_times": _zones({"Z5": 1200.0}),
                "sources": {"heart_rate_zone_times": "Garmin Connect"},
            },
        ],
        {"act_local": LOCAL},
    )


class WithZoneTimesTests(unittest.TestCase):
    def test_stored_local_zone_times_win_and_mark_the_model(self) -> None:
        local, watch = _summaries()

        self.assertEqual(LOCAL["heart_rate"], local["heart_rate_zone_times"])
        self.assertEqual(LOCAL["pace"], local["pace_zone_times"])
        self.assertEqual(
            {"heart_rate_zone_times": "local", "pace_zone_times": "local"},
            local["zone_models"],
        )
        self.assertEqual(
            "Zoneneinstellungen", local["sources"]["heart_rate_zone_times"]
        )
        self.assertEqual({"heart_rate_zone_times": "provider"}, watch["zone_models"])
        self.assertEqual("Garmin Connect", watch["sources"]["heart_rate_zone_times"])

    def test_a_session_without_zone_times_gets_no_marker(self) -> None:
        (row,) = with_zone_times([{"id": "act_1", "sport": "run"}], {})

        self.assertNotIn("zone_models", row)

    def test_malformed_stored_zones_are_ignored(self) -> None:
        (row,) = with_zone_times(
            [{"id": "act_1", "sport": "run"}],
            {"act_1": {"heart_rate": [{"id": "Z1", "secs": "x"}], "power": []}},
        )

        self.assertNotIn("heart_rate_zone_times", row)
        self.assertNotIn("zone_models", row)


class ZoneModelReportTests(unittest.TestCase):
    def test_distribution_never_adds_seconds_of_two_models(self) -> None:
        reports = zone_distribution(_summaries())

        heart_rate = {
            row["zone_model"]: row for row in reports if row["sensor"] == "heart_rate"
        }
        self.assertEqual({"Z1": 600.0, "Z2": 1200.0}, heart_rate["local"]["seconds"])
        self.assertEqual("Zoneneinstellungen", heart_rate["local"]["source"])
        self.assertEqual(1, heart_rate["local"]["measured_sessions"])
        self.assertEqual({"Z5": 1200.0}, heart_rate["provider"]["seconds"])
        self.assertEqual("Garmin Connect", heart_rate["provider"]["source"])
        self.assertEqual(2, heart_rate["provider"]["total_sessions"])
        (pace,) = [row for row in reports if row["sensor"] == "pace"]
        self.assertEqual("local", pace["zone_model"])

    def test_three_zone_intensity_counts_local_zones_only(self) -> None:
        result = intensity_3zone(_summaries())

        self.assertEqual({"low": 1800, "moderate": 0, "high": 0}, result["seconds"])
        self.assertEqual(1, result["measured_sessions"])
        self.assertEqual(2, result["total_sessions"])


if __name__ == "__main__":
    unittest.main()
