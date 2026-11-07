from __future__ import annotations

import unittest

from backend.activities.duplicates import deduplicate_api_records


class ApiRecordDeduplicationTests(unittest.TestCase):
    def test_keeps_order_and_unidentified_rows(self):
        unidentified = {"name": "no id"}
        scalar = "provider marker"
        records = [
            {"id": 1, "name": "first"},
            {"activityId": "1", "name": "duplicate"},
            unidentified,
            scalar,
            {"external_id": "two"},
            {"id": "two"},
        ]

        result = deduplicate_api_records(records)

        self.assertEqual(result, [records[0], unidentified, scalar, records[4]])
        self.assertIs(result[1], unidentified)


if __name__ == "__main__":
    unittest.main()
