from __future__ import annotations

import unittest

from backend.activities.duplicates import (
    duplicate_delete_action,
    validate_duplicate_delete,
)
from backend.errors import AppError


class DuplicateDeleteActionTests(unittest.TestCase):
    def test_preview_matches_confirmation_contract(self):
        pair = {
            "canonical_id": "wahoo-1",
            "canonical_name": "Wahoo ride",
            "duplicate_id": "garmin-1",
            "duplicate_name": "Garmin ride",
            "start_date_local": "2026-09-20T07:12:00",
            "snapshot_synced_at": "2026-09-20T08:00:00Z",
        }

        self.assertEqual(
            duplicate_delete_action(pair),
            {
                "action_type": "delete_duplicate_intervals_activity",
                "target_system": "intervals",
                "object_ids": {
                    "keep_activity_id": "wahoo-1",
                    "delete_activity_id": "garmin-1",
                },
                "diff": [
                    {
                        "type": "delete",
                        "id": "garmin-1",
                        "name": "Garmin ride",
                        "date": "2026-09-20",
                        "source": "Garmin",
                        "kept_source": "Wahoo",
                    }
                ],
                "payload": {
                    "canonical_id": "wahoo-1",
                    "duplicate_id": "garmin-1",
                    "snapshot_synced_at": "2026-09-20T08:00:00Z",
                },
            },
        )

    def test_validate_returns_exact_ids_for_current_snapshot(self):
        payload = {
            "canonical_id": "wahoo-1",
            "duplicate_id": "garmin-1",
            "snapshot_synced_at": "2026-09-20T08:00:00Z",
        }

        self.assertEqual(
            validate_duplicate_delete(payload, dict(payload)), ("wahoo-1", "garmin-1")
        )

    def test_validate_allows_snapshot_timestamp_missing_on_both_sides(self):
        payload = {"canonical_id": "wahoo-1", "duplicate_id": "garmin-1"}
        current = {"canonical_id": "wahoo-1", "duplicate_id": "garmin-1"}

        self.assertEqual(
            validate_duplicate_delete(payload, current), ("wahoo-1", "garmin-1")
        )

    def test_validate_rejects_missing_and_stale_values(self):
        current = {
            "canonical_id": "wahoo-1",
            "duplicate_id": "garmin-1",
            "snapshot_synced_at": "2026-09-20T08:00:00Z",
        }
        stale_values = [None]
        stale_values.extend({**current, key: "stale"} for key in current)
        stale_values.extend({**current, key: None} for key in current)
        stale_values.append({**current, "canonical_id": 1})

        for payload in stale_values:
            with self.subTest(payload=payload):
                with self.assertRaises(AppError) as raised:
                    validate_duplicate_delete(payload, current)
                self.assertEqual(raised.exception.status, 409)
                self.assertEqual(
                    raised.exception.message,
                    "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell. "
                    "Bitte die letzte Einheit erneut analysieren.",
                )

        with self.assertRaises(AppError):
            validate_duplicate_delete(current, None)


if __name__ == "__main__":
    unittest.main()
