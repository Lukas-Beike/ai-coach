"""The Garmin training-load projection gives the same result from canonical values.

Each case maps a synthetic Garmin snapshot with the production health mapper,
reads the observations through ``read_garmin_state`` and compares the projection
with the snapshot path. No account, network or real data is used.
"""

from __future__ import annotations

import copy
import unittest
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import MetricKind
from backend.performance.garmin_canonical import read_garmin_state
from backend.performance.garmin_projection import garmin_training_load_projection
from backend.providers.garmin_health_mapping import map_garmin_health

TODAY = date(2026, 10, 6)
ZONE = ZoneInfo("Europe/Berlin")


class MappedReader:
    """Serves the observations the production mapper makes of ``sections``."""

    def __init__(self, sections: dict[str, Any]) -> None:
        self.records = map_garmin_health(
            sections, zone=ZONE, retrieved_at=datetime(2026, 10, 6, 8, tzinfo=UTC)
        ).records

    def observations(self, db: Any, kind: MetricKind, **_: Any) -> tuple:
        return tuple(record for record in self.records if record.kind is kind)


def snapshot(freshness: str = "current", day: str = "2026-10-06") -> dict:
    return {
        "training_load_balance": {
            "metricsTrainingLoadBalanceDTOMap": {
                "device-a": {
                    "primaryTrainingDevice": True,
                    "calendarDate": day,
                    "monthlyLoadAerobicLow": 75,
                    "monthlyLoadAerobicLowTargetMin": 40,
                    "monthlyLoadAnaerobic": 0,
                    "monthlyLoadAnaerobicTargetMax": 20.5,
                }
            }
        },
        "daily_training_status": {
            "latestTrainingStatusData": {
                "device-a": {
                    "primaryTrainingDevice": True,
                    "calendarDate": day,
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 110,
                        "dailyTrainingLoadChronic": 95,
                        "dailyAcuteChronicWorkloadRatio": 1.15,
                    },
                }
            }
        },
        "source_freshness": {
            section: {
                "freshness": freshness,
                "observed_at": day,
                "fetched_at": "2026-10-06T08:00:00Z",
            }
            for section in ("training_load_balance", "daily_training_status")
        },
    }


class TrainingLoadParityTests(unittest.TestCase):
    def assert_parity(self, garmin: dict[str, Any]) -> dict[str, Any]:
        legacy = garmin_training_load_projection(garmin, TODAY)
        metrics = read_garmin_state(MappedReader(garmin), None).metrics
        # Only the sync status stays on the snapshot.
        status_only = {"source_freshness": copy.deepcopy(garmin["source_freshness"])}
        canonical = garmin_training_load_projection(status_only, TODAY, metrics)
        self.assertEqual(canonical, legacy)
        return canonical

    def test_fresh_values_of_today(self) -> None:
        result = self.assert_parity(snapshot())
        self.assertEqual(result["daily_status"]["acute_load"], 110)
        self.assertEqual(result["four_week_balance"]["monthlyLoadAnaerobic"], 0)

    def test_stale_or_older_values_are_dated_but_hidden(self) -> None:
        for garmin in (snapshot("stale"), snapshot(day="2026-10-05")):
            with self.subTest(garmin=garmin["source_freshness"]):
                result = self.assert_parity(garmin)
                self.assertIsNone(result["daily_status"]["acute_load"])

    def test_without_values_there_is_no_section(self) -> None:
        self.assertEqual(
            self.assert_parity({"source_freshness": {}}),
            {},
        )


if __name__ == "__main__":
    unittest.main()
