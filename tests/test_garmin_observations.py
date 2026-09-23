import copy
import unittest
from datetime import date, datetime, timezone

from backend.performance.garmin_observations import (
    garmin_record_observation_date,
    garmin_sleep_observation_date,
    garmin_sleep_ready_for_checkin,
    garmin_source_observed_at,
)


class GarminObservationTests(unittest.TestCase):
    def test_record_date_supports_all_existing_fields_and_millisecond_epoch(self):
        fields = (
            "calendarDate",
            "summaryDate",
            "date",
            "measurementDate",
            "timestampGMT",
            "timestamp",
            "startTimeLocal",
            "startTimeGMT",
        )
        for field in fields:
            with self.subTest(field=field):
                value = "2026-09-04T05:45:00.123Z"
                if field == "timestamp":
                    value = int(
                        datetime(2026, 9, 4, 5, 45, tzinfo=timezone.utc).timestamp()
                        * 1000
                    )
                self.assertEqual(
                    garmin_record_observation_date({field: value}), "2026-09-04"
                )

    def test_nested_source_uses_newest_valid_date_without_mutation(self):
        source = {
            "calendarDate": "not-a-date",
            "nested": [
                {"summaryDate": "2026-09-03"},
                {"startTimeGMT": "2026-09-05T06:00:00+00:00"},
                {
                    "timestamp": int(
                        datetime(2026, 9, 6, tzinfo=timezone.utc).timestamp() * 1000
                    )
                },
            ],
        }
        original = copy.deepcopy(source)
        self.assertEqual(garmin_source_observed_at(source), "2026-09-06")
        self.assertEqual(source, original)

    def test_deep_lists_are_traversed_iteratively(self):
        value = {"calendarDate": "2026-09-01"}
        for _ in range(1200):
            value = [value]
        self.assertEqual(garmin_source_observed_at(value), "2026-09-01")

    def test_invalid_values_are_rejected(self):
        self.assertIsNone(garmin_record_observation_date(None))  # type: ignore[arg-type]
        self.assertIsNone(garmin_record_observation_date({"date": "invalid"}))
        self.assertIsNone(
            garmin_record_observation_date(
                {"calendarDate": "invalid", "date": "2026-09-04"}
            )
        )
        self.assertIsNone(garmin_record_observation_date({"date": 1_700_000_000}))
        self.assertIsNone(
            garmin_source_observed_at({"date": None, "nested": ["invalid"]})
        )
        self.assertIsNone(garmin_sleep_observation_date(None))  # type: ignore[arg-type]

    def test_freshness_date_has_priority_over_raw_sleep(self):
        snapshot = {
            "sleep": {"dailySleepDTO": {"calendarDate": "2026-09-06"}},
            "source_freshness": {
                "sleep": {"observed_at": "2026-09-04T07:00:00Z", "freshness": "current"}
            },
        }
        self.assertEqual(garmin_sleep_observation_date(snapshot), "2026-09-04")

    def test_malformed_freshness_value_is_authoritative_without_raw_fallback(self):
        snapshot = {
            "sleep": {"dailySleepDTO": {"calendarDate": "2026-09-04"}},
            "source_freshness": {"sleep": {"observed_at": "malformed-value"}},
        }
        self.assertEqual(garmin_sleep_observation_date(snapshot), "malformed-")
        self.assertFalse(garmin_sleep_ready_for_checkin(date(2026, 9, 4), snapshot))

    def test_sleep_readiness_accepts_current_and_partial_only_for_matching_day(self):
        for freshness in ("current", "partial"):
            with self.subTest(freshness=freshness):
                snapshot = {
                    "source_freshness": {
                        "sleep": {"observed_at": "2026-09-04", "freshness": freshness}
                    }
                }
                self.assertTrue(
                    garmin_sleep_ready_for_checkin(date(2026, 9, 4), snapshot)
                )
        stale = {
            "source_freshness": {
                "sleep": {"observed_at": "2026-09-04", "freshness": "stale"}
            }
        }
        wrong_day = {
            "source_freshness": {
                "sleep": {"observed_at": "2026-09-03", "freshness": "current"}
            }
        }
        missing = {"source_freshness": {"sleep": {"freshness": "current"}}}
        self.assertFalse(garmin_sleep_ready_for_checkin(date(2026, 9, 4), stale))
        self.assertFalse(garmin_sleep_ready_for_checkin(date(2026, 9, 4), wrong_day))
        self.assertFalse(garmin_sleep_ready_for_checkin(date(2026, 9, 4), missing))

    def test_sleep_readiness_rejects_invalid_snapshot_and_checkin_date(self):
        self.assertFalse(garmin_sleep_ready_for_checkin(date(2026, 9, 4), None))  # type: ignore[arg-type]
        self.assertFalse(garmin_sleep_ready_for_checkin("2026-09-04", {}))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
