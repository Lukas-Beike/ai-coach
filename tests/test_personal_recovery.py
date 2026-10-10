import unittest
from datetime import date, datetime, timedelta, timezone

from backend.athlete.profile import normalize_profile
from backend.errors import AppError
from backend.performance.personal_recovery import personal_recovery


class PersonalRecoveryTests(unittest.TestCase):
    today = date(2026, 10, 2)

    def rows(self, nights):
        return [
            {
                "id": (self.today - timedelta(days=i)).isoformat(),
                "sleepSecs": 7 * 3600,
                "restingHR": 50,
                "hrv": 40,
            }
            for i in range(nights + 1)
        ]

    def test_coverage_and_excluding_current_value_from_baseline(self):
        for nights, status in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (28, "ok"),
        ):
            rows = self.rows(nights)
            rows[0]["restingHR"] = 100
            result = personal_recovery(rows, {}, {}, self.today)
            pulse = next(
                row for row in result["baselines"] if row["metric"] == "resting_hr"
            )
            self.assertEqual(status, pulse["status"])
            if nights >= 14:
                self.assertEqual(50, pulse["median"])
                self.assertEqual("above", pulse["position"])
            hrv = next(row for row in result["baselines"] if row["metric"] == "hrv")
            self.assertEqual(("RMSSD", status), (hrv["measurement"], hrv["status"]))

    def test_future_stale_and_separate_hrv_methods_are_not_classified(self):
        rows = self.rows(30)
        for row in rows:
            row["hrvSDNN"] = 30
        rows.append(
            {
                "id": "2026-10-03",
                "restingHR": 200,
                "sleepSecs": 100,
                "hrv": 200,
                "hrvSDNN": 200,
            }
        )
        result = personal_recovery(rows, {}, {}, self.today)
        self.assertEqual(
            {"RMSSD", "SDNN"},
            {
                row["measurement"]
                for row in result["baselines"]
                if row["metric"] == "hrv"
            },
        )
        self.assertFalse(
            any(
                point["date"] > "2026-10-02"
                for row in result["baselines"]
                for point in row["history"]
            )
        )
        stale = personal_recovery(self.rows(30)[3:], {}, {}, self.today)
        self.assertTrue(
            all(row["status"] == "insufficient_data" for row in stale["baselines"])
        )

    def test_legacy_hrv_method_field_is_ignored(self):
        rows = self.rows(14)
        for row in rows:
            row["hrv_method"] = "SDNN"
        result = personal_recovery(rows, {}, {}, self.today)
        self.assertEqual(
            ["RMSSD"],
            [
                row["measurement"]
                for row in result["baselines"]
                if row["metric"] == "hrv"
            ],
        )

    def test_deficit_uses_known_nights_and_never_offsets_with_long_sleep(self):
        rows = self.rows(5)
        rows[0]["sleepSecs"] = 10 * 3600
        result = personal_recovery(rows, {}, {"sleep_target_hours": "8"}, self.today)
        deficit = result["sleep_deficits"][0]
        self.assertEqual(
            (5, 6, "partial"),
            (deficit["deficit_hours"], deficit["known_nights"], deficit["status"]),
        )
        self.assertEqual(
            [], personal_recovery(rows, {}, {}, self.today)["sleep_deficits"]
        )

    def test_profile_target_requires_valid_explicit_value(self):
        self.assertEqual(
            "8", normalize_profile({"sleep_target_hours": 8})["sleep_target_hours"]
        )
        for value in (3, 13, "nan", "no"):
            with self.subTest(value=value), self.assertRaises(AppError):
                normalize_profile({"sleep_target_hours": value})

    def test_eight_calendar_weeks_keep_a_42_day_comparison_range(self):
        rows = self.rows(60)
        for row in rows:
            if row["id"] < "2026-08-21":
                row["restingHR"] = 100
        result = personal_recovery(rows, {}, {}, self.today)
        pulse = next(
            row for row in result["baselines"] if row["metric"] == "resting_hr"
        )
        self.assertEqual("2026-08-03", pulse["history"][0]["date"])
        self.assertEqual(61, len(pulse["history"]))
        self.assertEqual(42, pulse["nights"])
        self.assertEqual(50, pulse["median"])

    def sleep_rows(
        self, count, *, start="2026-09-01T21:30:00Z", end="2026-09-02T05:30:00Z"
    ):
        from datetime import datetime, timezone

        result = []
        for index in range(count):
            day = self.today - timedelta(days=count - index)
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(
                days=index
            )
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) + timedelta(
                days=index
            )
            result.append(
                {
                    "calendarDate": day.isoformat(),
                    "sleepStartTimestampGMT": int(
                        start_dt.replace(tzinfo=timezone.utc).timestamp() * 1000
                    ),
                    "sleepEndTimestampGMT": int(
                        end_dt.replace(tzinfo=timezone.utc).timestamp() * 1000
                    ),
                }
            )
        current_start = datetime.combine(
            self.today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        ).replace(hour=21, minute=30)
        current_end = datetime.combine(
            self.today, datetime.min.time(), tzinfo=timezone.utc
        ).replace(hour=5, minute=30)
        result.append(
            {
                "calendarDate": self.today.isoformat(),
                "sleepStartTimestampGMT": int(current_start.timestamp() * 1000),
                "sleepEndTimestampGMT": int(current_end.timestamp() * 1000),
            }
        )
        return result

    def test_sleep_regularity_coverage_thresholds_and_display_contract(self):
        for nights, expected in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (27, "provisional"),
            (28, "ok"),
        ):
            with self.subTest(nights=nights):
                result = personal_recovery(
                    [],
                    {"sleep": self.sleep_rows(nights)},
                    {"timezone": "UTC"},
                    self.today,
                )["regularity"]
                item = result["series"][0]
                self.assertEqual(expected, item["status"])
                self.assertEqual(nights, item["coverage"]["baseline_nights"])
                self.assertEqual(14, len(item["points_14"]))
                self.assertEqual(84, len(item["points_84"]))
                self.assertEqual("Garmin Connect", item["source"])
                self.assertTrue(item["method"].startswith("sleepStartTimestampGMT/"))

    def test_sleep_regularity_circular_midnight_median_and_source_separation(self):
        rows = self.sleep_rows(
            14, start="2026-09-01T21:50:00Z", end="2026-09-02T05:50:00Z"
        )
        rows[1]["sleepStartTimestampGMT"] = int(
            datetime(2026, 9, 1, 22, 10, tzinfo=timezone.utc).timestamp() * 1000
        )
        rows[1]["sleepEndTimestampGMT"] = int(
            datetime(2026, 9, 2, 6, 10, tzinfo=timezone.utc).timestamp() * 1000
        )
        result = personal_recovery(
            [], {"sleep": rows}, {"timezone": "UTC"}, self.today
        )["regularity"]
        self.assertEqual(
            0, result["series"][0]["baseline"]["onset_deviation_median_minutes"]
        )
        self.assertEqual(
            {"Garmin Connect"}, {item["source"] for item in result["series"]}
        )

    def test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration(
        self,
    ):
        malformed = [
            {
                "calendarDate": "2026-10-01",
                "sleepStartTimestampGMT": "2026-10-01T22:00:00Z",
            },
            {
                "calendarDate": "2026-10-01",
                "sleepStartTimestampGMT": "2026-10-02T05:00:00Z",
                "sleepEndTimestampGMT": "2026-10-02T04:00:00Z",
            },
            {
                "calendarDate": "2026-10-03",
                "sleepStartTimestampGMT": "2026-10-02T22:00:00Z",
                "sleepEndTimestampGMT": "2026-10-03T06:00:00Z",
            },
        ]
        sleep = [
            {
                "sleepStartTimestampGMT": "2026-09-28T21:00:00Z",
                "sleepEndTimestampGMT": "2026-09-29T04:00:00Z",
            },
            *malformed,
        ]
        item = personal_recovery(
            [], {"sleep": sleep}, {"timezone": "Europe/Berlin"}, self.today
        )["regularity"]["series"][0]
        observed = next(
            point for point in item["points"] if point["date"] == "2026-09-29"
        )
        self.assertEqual(7, observed["duration_hours"])
        self.assertEqual("2026-09-28T23:00:00+02:00", observed["onset_at"])
        self.assertEqual(1, len(item["points"]))


if __name__ == "__main__":
    unittest.main()
