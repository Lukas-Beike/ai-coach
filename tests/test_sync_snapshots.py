from __future__ import annotations

import copy
import json
import unittest

from backend.sync.snapshots import (
    latest_snapshot,
    merge_historical_snapshot,
    merge_performance_snapshot,
    save_snapshot,
)


class _Repository:
    def __init__(self):
        self.payload = None

    def latest_payload(self, db):
        return self.payload

    def save(self, db, snapshot, created_at):
        self.payload = json.dumps(snapshot)


class SnapshotPersistenceTests(unittest.TestCase):
    def test_snapshot_operations_use_caller_connection_and_store(self):
        repository = _Repository()
        values = {}
        snapshot = {"synced_at": "2026-01-01T00:00:00+00:00", "activities": []}

        save_snapshot(
            object(),
            snapshot,
            repository,
            update_full_sync=True,
            activity_days=14,
            set_value=lambda key, value, db: values.__setitem__(key, value),
        )

        self.assertEqual(latest_snapshot(object(), repository), snapshot)
        self.assertEqual(values["last_sync_at"], snapshot["synced_at"])
        self.assertEqual(values["last_sync_activity_days"], "14")


class SnapshotMergeTests(unittest.TestCase):
    def test_performance_merge_preserves_fields_and_deduplicates_incoming_first(self):
        current = {
            "synced_at": "old",
            "athlete": {"id": "old"},
            "recent_activities": [{"id": "activity"}],
            "recent_wellness": [{"id": "same", "value": "current"}, {"id": "current"}],
            "unknown_top_level": {"preserved": True},
            "raw_provider_data": {
                "athlete": {"id": "old"},
                "activities": [{"id": "raw-activity"}],
                "wellness": [{"id": "same", "value": "current"}, {"id": "raw-current"}],
                "unknown_raw": {"preserved": True},
            },
            "provider_sync": {
                "provider_marker": "preserved",
                "pagination": {
                    "activities": {"cursor": "activity-cursor"},
                    "performance_wellness": {"cursor": "old"},
                },
            },
        }
        performance = {
            "synced_at": "new",
            "athlete": {"id": "new"},
            "recent_wellness": [
                {"id": "same", "value": "incoming"},
                {"id": "incoming"},
            ],
            "raw_provider_data": {
                "athlete": {"id": "new"},
                "wellness": [
                    {"id": "same", "value": "incoming"},
                    {"id": "raw-incoming"},
                ],
            },
            "provider_sync": {
                "provider_marker": "ignored",
                "pagination": {
                    "performance_wellness": {"cursor": "new"},
                    "other": {"cursor": "ignored"},
                },
            },
        }
        original_current = copy.deepcopy(current)
        original_performance = copy.deepcopy(performance)

        result = merge_performance_snapshot(current, performance)

        self.assertIsNot(result, current)
        self.assertEqual(result["synced_at"], "new")
        self.assertEqual(result["athlete"], {"id": "new"})
        self.assertEqual(result["recent_activities"], [{"id": "activity"}])
        self.assertEqual(result["unknown_top_level"], {"preserved": True})
        self.assertEqual(
            result["recent_wellness"],
            [
                {"id": "same", "value": "incoming"},
                {"id": "incoming"},
                {"id": "current"},
            ],
        )
        self.assertEqual(result["raw_provider_data"]["athlete"], {"id": "new"})
        self.assertEqual(
            result["raw_provider_data"]["wellness"],
            [
                {"id": "same", "value": "incoming"},
                {"id": "raw-incoming"},
                {"id": "raw-current"},
            ],
        )
        self.assertEqual(
            result["raw_provider_data"]["unknown_raw"], {"preserved": True}
        )
        self.assertEqual(result["provider_sync"]["provider_marker"], "preserved")
        self.assertEqual(
            result["provider_sync"]["pagination"],
            {
                "activities": {"cursor": "activity-cursor"},
                "performance_wellness": {"cursor": "new"},
            },
        )
        self.assertEqual(current, original_current)
        self.assertEqual(performance, original_performance)

    def test_performance_merge_handles_missing_snapshot_sections_and_none_current(self):
        performance = {"synced_at": "new"}
        result = merge_performance_snapshot(None, performance)

        self.assertEqual(result["synced_at"], "new")
        self.assertEqual(result["athlete"], {})
        self.assertEqual(result["recent_wellness"], [])
        self.assertEqual(result["raw_provider_data"], {"wellness": []})
        self.assertEqual(result["provider_sync"], {"pagination": {}})

        pair_sequence = [("extra", "kept")]
        self.assertEqual(
            merge_performance_snapshot(pair_sequence, performance)["extra"], "kept"
        )

    def test_historical_merge_returns_input_when_current_is_not_a_dict(self):
        historical = {"synced_at": "historical"}
        for current in (None, "not-a-snapshot", 0):
            with self.subTest(current=current):
                self.assertIs(
                    merge_historical_snapshot(current, historical), historical
                )

    def test_historical_merge_copies_current_and_keeps_current_precedence(self):
        current = {
            "synced_at": "current",
            "unknown_top_level": {"kept": True},
            "raw_provider_data": {
                "athlete": {"id": "current"},
                "activities": [{"id": "same", "value": "current"}, {"id": "current"}],
                "wellness": [{"id": "wellness-current"}],
                "upcoming_calendar": [{"id": "calendar-current"}],
                "discarded_raw_key": "not-in-contract",
            },
            "provider_sync": {"pagination": {"current": "preserved"}},
        }
        historical = {
            "synced_at": "historical",
            "raw_provider_data": {
                "athlete": {"id": "historical"},
                "activities": [
                    {"id": "same", "value": "historical"},
                    {"id": "historical"},
                ],
                "wellness": [{"id": "wellness-current"}, {"id": "wellness-historical"}],
                "upcoming_calendar": [{"id": "calendar-historical"}],
            },
            "provider_sync": {"calendar_window": {"start": "2000-01-01"}},
        }
        original_current = copy.deepcopy(current)
        original_historical = copy.deepcopy(historical)

        result = merge_historical_snapshot(current, historical)

        self.assertIsNot(result, current)
        self.assertIsNot(result["raw_provider_data"], current["raw_provider_data"])
        self.assertEqual(result["unknown_top_level"], {"kept": True})
        self.assertEqual(
            result["raw_provider_data"],
            {
                "athlete": {"id": "current"},
                "activities": [
                    {"id": "same", "value": "current"},
                    {"id": "current"},
                    {"id": "historical"},
                ],
                "wellness": [
                    {"id": "wellness-current"},
                    {"id": "wellness-historical"},
                ],
                "upcoming_calendar": [{"id": "calendar-current"}],
            },
        )
        self.assertEqual(
            result["historical_sync"],
            {
                "synced_at": "historical",
                "window": {"start": "2000-01-01"},
            },
        )
        self.assertEqual(
            result["provider_sync"], {"pagination": {"current": "preserved"}}
        )
        self.assertEqual(current, original_current)
        self.assertEqual(historical, original_historical)

    def test_historical_merge_defaults_missing_raw_and_provider_sections(self):
        current = {"raw_provider_data": {"activities": [{"id": "current"}]}}
        result = merge_historical_snapshot(current, {"synced_at": "historical"})

        self.assertEqual(
            result["raw_provider_data"],
            {
                "athlete": {},
                "activities": [{"id": "current"}],
                "wellness": [],
                "upcoming_calendar": [],
            },
        )
        self.assertEqual(
            result["historical_sync"], {"synced_at": "historical", "window": {}}
        )


if __name__ == "__main__":
    unittest.main()
