from __future__ import annotations

import unittest
from copy import deepcopy

from backend.activities.duplicates import (
    duplicate_delete_action,
    remove_activity_from_snapshot,
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


class RemoveActivityFromSnapshotTests(unittest.TestCase):
    def test_removes_exact_id_and_activity_id_matches_without_mutating_input(self):
        snapshot = {
            "synced_at": "old",
            "recent_activities": [
                {"id": "delete-me", "source": "Garmin"},
                {"activityId": "delete-me", "source": "Garmin"},
                {"id": "delete-me-extra", "source": "Wahoo"},
                {"id": "keep-me", "source": "Wahoo"},
                "malformed row",
            ],
            "raw_provider_data": {
                "provider": "Intervals",
                "activities": [
                    {"activityId": "delete-me", "source": "Garmin"},
                    {"id": "keep-me", "source": "Wahoo"},
                ],
                "other": {"preserved": True},
            },
            "other": {"preserved": True},
        }
        original = deepcopy(snapshot)

        result = remove_activity_from_snapshot(snapshot, "delete-me", synced_at="new")

        self.assertEqual(
            result["recent_activities"],
            [
                {"id": "delete-me-extra", "source": "Wahoo"},
                {"id": "keep-me", "source": "Wahoo"},
                "malformed row",
            ],
        )
        self.assertEqual(
            result["raw_provider_data"]["activities"],
            [{"id": "keep-me", "source": "Wahoo"}],
        )
        self.assertEqual(result["raw_provider_data"]["other"], {"preserved": True})
        self.assertEqual(result["other"], {"preserved": True})
        self.assertEqual(result["synced_at"], "new")
        self.assertEqual(snapshot, original)

    def test_matches_numeric_ids_using_the_first_present_alias(self):
        snapshot = {
            "recent_activities": [
                {"id": 123},
                {"activityId": 123},
                {"id": "other", "activityId": 123},
            ],
            "raw_provider_data": {"activities": [{"activityId": 123}, {"id": 456}]},
        }

        result = remove_activity_from_snapshot(snapshot, "123", synced_at="new")

        self.assertEqual(
            result["recent_activities"], [{"id": "other", "activityId": 123}]
        )
        self.assertEqual(result["raw_provider_data"]["activities"], [{"id": 456}])

    def test_handles_absent_and_malformed_raw_activity_data(self):
        without_raw = {"recent_activities": [{"id": "keep-me"}]}
        result_without_raw = remove_activity_from_snapshot(
            without_raw, "delete-me", synced_at="new"
        )
        self.assertNotIn("raw_provider_data", result_without_raw)

        for raw in (None, "malformed"):
            with self.subTest(raw=raw):
                snapshot = {"raw_provider_data": raw}
                original = deepcopy(snapshot)
                result = remove_activity_from_snapshot(
                    snapshot, "delete-me", synced_at="new"
                )
                self.assertEqual(result["raw_provider_data"], raw)
                self.assertEqual(snapshot, original)
                self.assertEqual(result["synced_at"], "new")

        for raw in ({"activities": "malformed", "other": 1}, {}):
            with self.subTest(raw=raw):
                snapshot = {"raw_provider_data": raw}
                original = deepcopy(snapshot)
                result = remove_activity_from_snapshot(
                    snapshot, "delete-me", synced_at="new"
                )
                self.assertEqual(result["raw_provider_data"], {**raw, "activities": []})
                self.assertEqual(snapshot, original)
                self.assertEqual(result["synced_at"], "new")

    def test_non_list_recent_activities_becomes_an_empty_list(self):
        for activities in (None, "malformed", {"id": "delete-me"}):
            with self.subTest(activities=activities):
                snapshot = {"recent_activities": activities}
                result = remove_activity_from_snapshot(
                    snapshot, "delete-me", synced_at="new"
                )
                self.assertEqual(result["recent_activities"], [])

        result = remove_activity_from_snapshot({}, "delete-me", synced_at="new")
        self.assertEqual(result["recent_activities"], [])

    def test_non_dict_snapshot_returns_none(self):
        self.assertIsNone(
            remove_activity_from_snapshot(None, "delete-me", synced_at="new")
        )


if __name__ == "__main__":
    unittest.main()
