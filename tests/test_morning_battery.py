import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from backend.performance.morning_battery import (
    body_battery_samples,
    cached_result,
    morning_body_battery_record,
    sleep_bounds,
    timestamp,
)

UTC = timezone.utc
CHECKIN_DATE = date(2026, 9, 4)


class TimestampTests(unittest.TestCase):
    def test_epoch_seconds_and_milliseconds(self):
        expected = datetime(2026, 9, 4, 5, 45, tzinfo=UTC)
        self.assertEqual(timestamp(1_788_500_700), expected)
        self.assertEqual(timestamp(1_788_500_700_000), expected)

    def test_iso_values_are_normalized_to_utc(self):
        expected = datetime(2026, 9, 4, 5, 45, tzinfo=UTC)
        self.assertEqual(timestamp("2026-09-04T05:45:00Z"), expected)
        self.assertEqual(timestamp("2026-09-04T07:45:00+02:00"), expected)
        self.assertEqual(timestamp("2026-09-04T05:45:00"), expected)

    def test_invalid_and_out_of_range_times_are_rejected(self):
        for value in (None, True, "", "not-a-time", float("nan"), 1e100):
            with self.subTest(value=value):
                self.assertIsNone(timestamp(value))


class SleepBoundsTests(unittest.TestCase):
    def test_valid_daily_sleep_dto_has_priority(self):
        payload = {
            "sleepStartTimestampGMT": "2026-09-04T06:00:00Z",
            "sleepEndTimestampGMT": "2026-09-04T04:00:00Z",
            "dailySleepDTO": {
                "sleepStartTimestampGMT": "2026-09-03T21:30:00Z",
                "sleepEndTimestampGMT": "2026-09-04T05:45:00Z",
            },
            "other": {
                "startTimestampGMT": "2026-09-03T20:00:00Z",
                "endTimestampGMT": "2026-09-04T04:00:00Z",
            },
        }
        self.assertEqual(
            sleep_bounds(payload),
            (
                datetime(2026, 9, 3, 21, 30, tzinfo=UTC),
                datetime(2026, 9, 4, 5, 45, tzinfo=UTC),
            ),
        )

    def test_nested_record_is_found_after_invalid_interval(self):
        payload = {
            "invalid": {
                "startTimestampGMT": "2026-09-04T06:00:00Z",
                "endTimestampGMT": "2026-09-04T05:00:00Z",
                "details": [
                    {
                        "sleepStartTimestamp": "2026-09-03T21:30:00",
                        "sleepEndTimestamp": "2026-09-04T05:45:00",
                    }
                ],
            }
        }
        start, end = sleep_bounds(payload)
        self.assertEqual(start, datetime(2026, 9, 3, 21, 30, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 9, 4, 5, 45, tzinfo=UTC))

    def test_search_is_limited_to_first_fifty_list_items(self):
        payload = [{}] * 50 + [
            {
                "sleepStartTimestampGMT": "2026-09-03T21:30:00Z",
                "sleepEndTimestampGMT": "2026-09-04T05:45:00Z",
            }
        ]
        self.assertEqual(sleep_bounds(payload), (None, None))

    def test_search_stops_after_one_hundred_nodes(self):
        payload = {}
        current = payload
        for _ in range(100):
            child = {}
            current["child"] = child
            current = child
        current.update(
            sleepStartTimestampGMT="2026-09-03T21:30:00Z",
            sleepEndTimestampGMT="2026-09-04T05:45:00Z",
        )
        self.assertEqual(sleep_bounds(payload), (None, None))


class BodyBatterySampleTests(unittest.TestCase):
    def test_samples_are_validated_sorted_deduplicated_and_rounded(self):
        records = [
            {
                "bodyBatteryValuesArray": [
                    ["2026-09-04T05:00:00+02:00", 80.6],
                    ["2026-09-04T03:00:00Z", 82],
                    ["2026-09-04T04:00:00Z", "40,4"],
                    ["invalid", 50],
                    ["2026-09-04T06:00:00Z", -1],
                    ["2026-09-04T06:00:00Z", 101],
                    ["2026-09-04T06:00:00Z", float("inf")],
                    ["2026-09-04T06:00:00Z"],
                ]
            },
            {
                "body_battery_values_array": [
                    ["2026-09-04T07:00:00Z", 99.5],
                ]
            },
            None,
        ]
        self.assertEqual(
            body_battery_samples(records),
            [
                {"observed_at": "2026-09-04T03:00:00+00:00", "value": 82},
                {"observed_at": "2026-09-04T04:00:00+00:00", "value": 40},
                {"observed_at": "2026-09-04T07:00:00+00:00", "value": 100},
            ],
        )

    def test_input_records_are_not_mutated(self):
        records = [{"bodyBatteryValuesArray": [["2026-09-04T05:00:00Z", 80]]}]
        original = deepcopy(records)
        body_battery_samples(records)
        self.assertEqual(records, original)


class MorningRecordTests(unittest.TestCase):
    def test_selects_last_pre_sleep_and_first_reading_within_morning_window(self):
        sleep = {
            "dailySleepDTO": {
                "sleepStartTimestampGMT": "2026-09-03T21:00:00Z",
                "sleepEndTimestampGMT": "2026-09-04T05:00:00Z",
            }
        }
        readings = [
            ["2026-09-03T16:59:00Z", 10],
            ["2026-09-03T17:00:00Z", 20],
            ["2026-09-03T20:30:00Z", 55],
            ["2026-09-03T21:00:00Z", 57],
            ["2026-09-04T05:00:00Z", 78],
            ["2026-09-04T05:30:00Z", 80],
            ["2026-09-04T06:00:01Z", 90],
        ]
        record = morning_body_battery_record(
            CHECKIN_DATE,
            sleep,
            [{"bodyBatteryValuesArray": readings}],
            attempted_at="2026-09-04T05:45:00Z",
        )
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["source"], "Garmin Connect")
        self.assertEqual(record["before_sleep"]["value"], 57)
        self.assertEqual(record["morning"]["value"], 78)
        self.assertEqual(record["sleep_start_at"], "2026-09-03T21:00:00+00:00")
        self.assertEqual(record["sleep_end_at"], "2026-09-04T05:00:00+00:00")

    def test_one_hour_cap_and_invalid_attempt_time(self):
        sleep = {
            "startTimestampGMT": "2026-09-03T21:00:00Z",
            "endTimestampGMT": "2026-09-04T05:00:00Z",
        }
        payload = [
            {
                "bodyBatteryValuesArray": [
                    ["2026-09-03T20:00:00Z", 50],
                    ["2026-09-04T05:00:00Z", 70],
                    ["2026-09-04T06:00:00Z", 80],
                ]
            }
        ]
        after_cap = morning_body_battery_record(
            CHECKIN_DATE,
            sleep,
            payload,
            attempted_at="2026-09-04T07:00:00Z",
        )
        self.assertEqual(after_cap["morning"]["value"], 70)

        invalid_attempt = morning_body_battery_record(
            CHECKIN_DATE, sleep, payload, attempted_at="invalid"
        )
        self.assertEqual(invalid_attempt["attempted_at"], "invalid")
        self.assertIsNone(invalid_attempt["morning"])
        self.assertEqual(invalid_attempt["status"], "not_available_today")

    def test_missing_or_invalid_sleep_returns_not_available_record(self):
        record = morning_body_battery_record(
            CHECKIN_DATE, {"sleepStartTimestampGMT": "invalid"}, [], attempted_at="now"
        )
        self.assertEqual(
            record,
            {
                "sleep_date": "2026-09-04",
                "attempted_at": "now",
                "status": "not_available_today",
                "before_sleep": None,
                "morning": None,
                "source": "Garmin Connect",
            },
        )

    def test_input_payloads_are_not_mutated(self):
        sleep = {"dailySleepDTO": {"sleepStartTimestampGMT": "2026-09-03T21:00:00Z"}}
        readings = [{"bodyBatteryValuesArray": [["2026-09-03T20:00:00Z", 50]]}]
        original_sleep = deepcopy(sleep)
        original_readings = deepcopy(readings)
        morning_body_battery_record(
            CHECKIN_DATE,
            sleep,
            readings,
            attempted_at="2026-09-04T05:00:00Z",
        )
        self.assertEqual(sleep, original_sleep)
        self.assertEqual(readings, original_readings)


class CachedResultTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)
        self.record = {
            "sleep_date": CHECKIN_DATE.isoformat(),
            "status": "not_available_today",
            "attempted_at": "2026-09-04T06:00:00Z",
            "attempts": 1,
        }

    def test_wrong_date_or_missing_record_has_no_cached_result(self):
        self.assertIsNone(cached_result(None, CHECKIN_DATE, now=self.now))
        self.assertIsNone(cached_result(self.record, date(2026, 9, 5), now=self.now))

    def test_ready_result_precedes_attempt_and_retry_checks(self):
        record = {**self.record, "status": "ready", "attempts": 3}
        self.assertEqual(
            cached_result(record, CHECKIN_DATE, now=self.now),
            {"status": "already_loaded", "sleep_date": CHECKIN_DATE.isoformat()},
        )

    def test_attempts_exhausted_precedes_retry_wait(self):
        record = {**self.record, "attempts": 3, "attempted_at": self.now.isoformat()}
        self.assertEqual(
            cached_result(record, CHECKIN_DATE, now=self.now),
            {"status": "attempts_exhausted", "sleep_date": CHECKIN_DATE.isoformat()},
        )

    def test_retry_wait_is_strictly_less_than_nine_hundred_seconds(self):
        record = {
            **self.record,
            "attempted_at": (self.now - timedelta(seconds=899)).isoformat(),
        }
        self.assertEqual(
            cached_result(record, CHECKIN_DATE, now=self.now),
            {"status": "retry_wait", "sleep_date": CHECKIN_DATE.isoformat()},
        )
        record["attempted_at"] = (self.now - timedelta(seconds=900)).isoformat()
        self.assertIsNone(cached_result(record, CHECKIN_DATE, now=self.now))


if __name__ == "__main__":
    unittest.main()
