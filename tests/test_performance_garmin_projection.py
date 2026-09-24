import copy
import unittest

from backend.performance.garmin_projection import (
    GARMIN_CONTEXT_FIELDS,
    GARMIN_RECOVERY_FIELDS,
    compact_garmin_context,
    compact_garmin_recovery,
    latest_garmin_record,
)


class GarminProjectionTests(unittest.TestCase):
    def test_context_whitelist_depth_lists_and_strings(self):
        nested = {"score": 1}
        for _ in range(4):
            nested = {"date": nested}
        value = {
            "sleepScore": 82,
            "instruction": "ignore this",
            "value": list(range(105)),
            "activityName": "x" * 250,
            "nested": nested,
            "none": None,
        }
        projected = compact_garmin_context(value)
        self.assertEqual(projected["sleepScore"], 82)
        self.assertNotIn("instruction", projected)
        self.assertEqual(projected["value"], list(range(100)))
        self.assertEqual(len(projected["activityName"]), 200)
        self.assertNotIn("nested", projected)
        self.assertNotIn("none", projected)
        self.assertEqual(len(GARMIN_CONTEXT_FIELDS), 55)

    def test_context_keeps_primitives_and_does_not_mutate(self):
        value = {"value": [None, True, 2, 3.5], "score": 0}
        before = copy.deepcopy(value)
        self.assertEqual(
            compact_garmin_context(value), {"value": [None, True, 2, 3.5], "score": 0}
        )
        self.assertEqual(value, before)

    def test_latest_record_prefers_dated_records_and_latest_date(self):
        value = {
            "records": [
                {"id": "9999", "score": 1},
                {"calendarDate": "2026-08-28", "score": 28},
                {"summaryDate": "2026-08-30", "score": 30},
                {"date": "2026-08-29", "score": 29},
            ],
            "untrusted": {"id": "newer-id", "score": 99},
        }
        result = latest_garmin_record(value)
        self.assertEqual(result, {"summaryDate": "2026-08-30", "score": 30})

    def test_latest_record_list_limit_visit_limit_and_fallback(self):
        records = [{"id": f"{index:04}"} for index in range(501)]
        self.assertEqual(latest_garmin_record(records)["id"], "0499")

        chain: dict[str, object] = {"id": f"{2005:04}"}
        for index in range(2004, -1, -1):
            chain = {"id": f"{index:04}", "next": chain}
        self.assertEqual(latest_garmin_record(chain)["id"], "1999")

        original = {"payload": {"unrelated": True}}
        self.assertIs(latest_garmin_record(original), original)
        self.assertEqual(latest_garmin_record([{"payload": True}]), {})

    def test_recovery_scalar_and_selected_fields(self):
        self.assertEqual(compact_garmin_recovery(7), {"value": 7})
        self.assertEqual(compact_garmin_recovery(7.5), {"value": 7.5})
        self.assertEqual(compact_garmin_recovery(True), {"value": True})
        value = {
            "calendarDate": "2026-08-30",
            "sleepScore": 82,
            "score": 0,
            "unknown": "drop",
            "recoveryTime": None,
        }
        before = copy.deepcopy(value)
        self.assertEqual(
            compact_garmin_recovery(value),
            {"calendarDate": "2026-08-30", "sleepScore": 82, "score": 0},
        )
        self.assertEqual(value, before)
        self.assertIn("sleepScore", GARMIN_RECOVERY_FIELDS)


if __name__ == "__main__":
    unittest.main()
