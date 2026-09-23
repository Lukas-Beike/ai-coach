"""Focused tests for Coach activity read-tool orchestration."""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import MagicMock, Mock

from backend.activities.read_service import ActivityReadService
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.errors import AppError


class CoachActivityReadToolServiceTests(unittest.TestCase):
    def test_recent_activities_applies_defaults_bounds_and_today(self):
        activity_read = Mock()
        activity_read.recent.return_value = {"activities": []}
        today = date(2026, 9, 23)
        service = CoachActivityReadToolService(
            activity_read, Mock(), Mock(), lambda: today
        )

        result = service.execute("list_recent_activities", {})

        self.assertEqual(result, {"ok": True, "activities": []})
        activity_read.recent.assert_called_once_with(30, 100, today=today)
        activity_read.reset_mock()
        service.execute("list_recent_activities", {"days": 9999, "limit": 0})
        activity_read.recent.assert_called_once_with(3660, 1, today=today)

    def test_recent_activities_invalid_values_preserve_app_error_contract(self):
        service = CoachActivityReadToolService(Mock(), Mock(), Mock(), date.today)

        for arguments in ({"days": "bad"}, {"limit": None}):
            with self.subTest(arguments=arguments), self.assertRaises(AppError) as caught:
                service.execute("list_recent_activities", arguments)
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(
                caught.exception.message,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            self.assertEqual(caught.exception.reason, "invalid_list_request")

    def test_detail_uses_local_sources_and_keeps_sanitized_detail_projection(self):
        raw_activity = {
            "id": "synthetic-1",
            "name": "Synthetic tempo",
            "type": "Run",
            "start_date_local": "2026-09-22T07:00:00",
            "average_speed": 3.2,
            "average_heartrate": 166,
            "average_watts": 245,
            "streams": {"watts": [200, 250], "latlng": [[1, 2], [3, 4]]},
            "provider_extra": "must not pass",
        }
        manager = MagicMock()
        manager.unit_of_work.return_value.__enter__.return_value = object()
        snapshot_repository = Mock()
        snapshot_repository.latest_payload.return_value = json.dumps({
            "synced_at": "synthetic-sync",
            "recent_activities": [{"id": "synthetic-1", "type": "Run"}],
            "raw_provider_data": {"activities": [raw_activity]},
        })
        feedback = Mock()
        feedback.list.return_value = []
        activity_read = ActivityReadService(manager, snapshot_repository, feedback)
        garmin_snapshot = {"recent_wellness": []}
        profile_value = {"weight_kg": "70"}
        garmin = Mock(snapshot=Mock(return_value=garmin_snapshot))
        profile = Mock(get=Mock(return_value=profile_value))
        today = date(2026, 9, 23)
        service = CoachActivityReadToolService(
            activity_read, garmin, profile, lambda: today
        )

        result = service.execute(
            "get_activity_details", {"activity_id": "synthetic-1"}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["snapshot_synced_at"], "synthetic-sync")
        self.assertEqual(result["activity"]["streams"], {"watts": [200, 250]})
        self.assertNotIn("id", result["activity"])
        self.assertNotIn("provider_extra", result["activity"])
        self.assertNotIn("latlng", result["activity"]["streams"])
        self.assertEqual(
            result["data_scope"],
            "bounded sanitized detail projection of exactly one Intervals.icu activity",
        )
        self.assertEqual(result["activity_validation"]["activity"]["activity_id"], "synthetic-1")
        garmin.snapshot.assert_called_once_with()
        profile.get.assert_called_once_with()

    def test_unknown_tool_is_unclaimed_and_invalid_detail_ids_keep_error(self):
        activity_read = Mock()
        service = CoachActivityReadToolService(activity_read, Mock(), Mock(), date.today)
        self.assertIsNone(service.execute("list_workout_library", {}))
        activity_read.detail.side_effect = AppError(
            400,
            "Die Aktivität konnte nicht eindeutig zugeordnet werden.",
            reason="invalid_activity_request",
        )

        with self.assertRaises(AppError) as caught:
            service.execute("get_activity_details", {"activity_id": " "})
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.reason, "invalid_activity_request")


if __name__ == "__main__":
    unittest.main()
