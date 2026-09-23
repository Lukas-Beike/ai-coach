import copy
import unittest
from datetime import date

from backend.performance.recovery import (
    dated_garmin_recovery_records,
    garmin_recovery_average,
    garmin_recovery_metric,
)


class GarminRecoveryTests(unittest.TestCase):
    def test_dated_records_use_field_priority_and_reject_invalid_first_date(self):
        value = [
            {"calendarDate": "invalid", "summaryDate": "2026-08-30", "score": 1},
            {"summaryDate": "2026-08-31T12:00:00Z", "score": 2},
            {"id": "2026-09-01", "score": 3},
        ]
        self.assertEqual(
            dated_garmin_recovery_records(value),
            [
                ("2026-09-01", value[2]),
                ("2026-08-31", value[1]),
            ],
        )

    def test_dated_records_have_lifo_dfs_order_and_visit_list_limits(self):
        entries = [
            {"date": f"2026-08-{index:02}", "score": index} for index in range(1, 32)
        ]
        result = dated_garmin_recovery_records({"entries": entries})
        self.assertEqual(result[0][0], "2026-08-31")
        self.assertEqual(result[-1][0], "2026-08-01")

        entries = [{"date": "2026-08-01", "score": index} for index in range(501)]
        result = dated_garmin_recovery_records(entries)
        self.assertEqual(len(result), 500)
        self.assertEqual(result[0][1]["score"], 499)

        chain: dict[str, object] = {"id": "2026-01-01"}
        for index in range(2004, -1, -1):
            chain = {"id": "2026-01-01", "next": chain}
        self.assertEqual(len(dated_garmin_recovery_records(chain)), 2000)

    def test_metric_chooses_newest_valid_record_and_normalizes_nested_keys(self):
        snapshot = {
            "recovery": [
                {"date": "2026-08-30", "nested": {"last-night-avg": 60}},
                {"date": "2026-08-31", "nested": {"lastNightAvg": None}},
                {"date": "2026-09-01", "nested": {"lastNightAvg": 70}},
            ]
        }
        self.assertEqual(
            garmin_recovery_metric(snapshot, "recovery", ("lastNightAvg",)),
            (70, "2026-09-01"),
        )
        self.assertEqual(
            garmin_recovery_metric(
                snapshot, "recovery", ("lastNightAvg", "last-night-avg")
            ),
            (70, "2026-09-01"),
        )

    def test_metric_last_numeric_excludes_bool_and_supports_transform_none(self):
        snapshot = {
            "recovery": [
                {
                    "date": "2026-08-30",
                    "score": {"value": True, "nested": {"score": 55}},
                },
                {"date": "2026-08-31", "score": {"value": False}},
            ]
        }
        self.assertEqual(
            garmin_recovery_metric(snapshot, "recovery", ("score",)),
            (55, "2026-08-30"),
        )
        self.assertEqual(
            garmin_recovery_metric(
                snapshot,
                "recovery",
                ("score",),
                transform=lambda value: None if value == 55 else value,
            ),
            (None, None),
        )

    def test_average_is_inclusive_and_rounded(self):
        snapshot = {
            "recovery": [
                {"date": "2026-08-29", "score": 100},
                {"date": "2026-08-30", "score": 1},
                {"date": "2026-08-31", "score": 2},
                {"date": "2026-09-01", "score": 2},
                {"date": "not-a-date", "score": 99},
            ]
        }
        self.assertEqual(
            garmin_recovery_average(
                snapshot, "recovery", ("score",), 2, date(2026, 8, 31)
            ),
            1.5,
        )
        self.assertEqual(
            garmin_recovery_average(
                snapshot,
                "recovery",
                ("score",),
                2,
                date(2026, 8, 31),
                transform=lambda value: float(value) / 3,
            ),
            0.5,
        )

    def test_inputs_are_not_mutated(self):
        snapshot = {"recovery": [{"date": "2026-08-31", "score": 70}]}
        before = copy.deepcopy(snapshot)
        dated_garmin_recovery_records(snapshot["recovery"])
        garmin_recovery_metric(snapshot, "recovery", ("score",))
        garmin_recovery_average(snapshot, "recovery", ("score",), 2, date(2026, 8, 31))
        self.assertEqual(snapshot, before)


if __name__ == "__main__":
    unittest.main()
