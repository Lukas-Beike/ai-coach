"""Focused tests for Coach activity read-tool orchestration."""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from backend.activities.read_service import ActivityReadService
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.errors import AppError


class CoachActivityReadToolServiceTests(unittest.TestCase):
    def test_report_defaults_to_requested_period_without_unrelated_analysis_reads(self):
        report = Mock()
        report.read.return_value = {"start": "2026-09-01", "totals": {"sessions": 2}}
        records = SimpleNamespace(endurance=Mock(), comparisons=Mock())
        derived = SimpleNamespace(
            impact=Mock(), body_history=Mock(), sleep_regularity=Mock()
        )
        reports = SimpleNamespace(
            report=report,
            records=records,
            derived=derived,
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute(
            "get_training_report", {"start": "2026-09-01", "days": 7}
        )
        self.assertEqual(result["report"]["totals"]["sessions"], 2)
        records.endurance.assert_not_called()
        derived.impact.assert_not_called()
        report.read.assert_called_once_with({"start": "2026-09-01", "days": 7}, "UTC")
        self.assertEqual(result["projection"]["requested_sections"], ["report"])

    def test_report_can_select_comparisons_and_rejects_unknown_section(self):
        report = Mock()
        records = SimpleNamespace(comparisons=Mock(), endurance=Mock())
        records.comparisons.return_value = {"status": "insufficient_data", "groups": []}
        reports = SimpleNamespace(
            report=report,
            records=records,
            derived=SimpleNamespace(
                impact=Mock(), body_history=Mock(), sleep_regularity=Mock()
            ),
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute("get_training_report", {"sections": ["comparisons"]})
        self.assertEqual(result["comparisons"]["status"], "insufficient_data")
        report.read.assert_not_called()
        with self.assertRaises(AppError):
            service.execute("get_training_report", {"sections": ["unknown"]})

    def test_report_can_select_body_history_and_sleep_regularity(self):
        report = Mock()
        derived = SimpleNamespace(body_history=Mock(), sleep_regularity=Mock())
        derived.body_history.return_value = {"weight": []}
        derived.sleep_regularity.return_value = {"status": "ok"}
        reports = SimpleNamespace(
            report=report,
            records=SimpleNamespace(endurance=Mock(), comparisons=Mock()),
            derived=derived,
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute(
            "get_training_report", {"sections": ["body_history", "sleep_regularity"]}
        )
        self.assertEqual(result["body_history"], {"weight": []})
        self.assertEqual(result["sleep_regularity"]["status"], "ok")
        report.read.assert_not_called()

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
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(AppError) as caught,
            ):
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
        snapshot_repository.latest_snapshot.return_value = {
            "synced_at": "synthetic-sync",
            "recent_activities": [{"id": "synthetic-1", "type": "Run"}],
            "raw_provider_data": {"activities": [raw_activity]},
        }
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

        result = service.execute("get_activity_details", {"activity_id": "synthetic-1"})

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
        self.assertEqual(
            result["activity_validation"]["activity"]["activity_id"], "synthetic-1"
        )
        garmin.snapshot.assert_called_once_with()
        profile.get.assert_called_once_with()

    def test_unknown_tool_is_unclaimed_and_invalid_detail_ids_keep_error(self):
        activity_read = Mock()
        service = CoachActivityReadToolService(
            activity_read, Mock(), Mock(), date.today
        )
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
