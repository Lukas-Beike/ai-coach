import copy
import unittest

from backend.performance.recovery import dated_garmin_recovery_records, rounded_average


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

    def test_inputs_are_not_mutated(self):
        snapshot = {"recovery": [{"date": "2026-08-31", "score": 70}]}
        before = copy.deepcopy(snapshot)
        dated_garmin_recovery_records(snapshot["recovery"])
        self.assertEqual(snapshot, before)

    def test_rounded_average_uses_two_decimals_and_none_for_no_values(self):
        self.assertEqual(rounded_average([7.0, 7.1, 7.15]), 7.08)
        self.assertIsNone(rounded_average([]))


if __name__ == "__main__":
    unittest.main()
