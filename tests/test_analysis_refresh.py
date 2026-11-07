import unittest
from datetime import date
from unittest.mock import Mock

from backend.errors import AppError
from backend.sync.analysis_refresh import AnalysisRefreshService


class AnalysisRefreshTests(unittest.TestCase):
    def make_service(self, today=date(2026, 10, 20)):
        garmin = Mock()
        garmin.refresh.return_value = {
            "status": "ok",
            "sources": {"activities": True},
        }
        return AnalysisRefreshService(lambda: garmin, lambda: today), garmin

    def test_sessions_refresh_the_bounded_garmin_activity_window(self):
        service, garmin = self.make_service()

        result = service.refresh("sessions")

        garmin.refresh.assert_called_once_with(
            "sessions", date(2026, 9, 9), date(2026, 10, 20)
        )
        self.assertEqual("ok", result["status"])
        self.assertEqual(["Garmin-Aktivitätsübersicht"], result["refreshed_sources"])
        self.assertEqual([], result["not_refreshed_sources"])
        self.assertEqual([], result["truncated_sources"])

    def test_recovery_refreshes_its_own_garmin_area_and_reports_partial_sources(self):
        service, garmin = self.make_service()
        garmin.refresh.return_value = {
            "status": "partial",
            "sources": {"sleep": True, "hrv": False},
        }

        result = service.refresh("recovery", days=84)

        garmin.refresh.assert_called_once_with(
            "recovery", date(2026, 7, 29), date(2026, 10, 20)
        )
        self.assertEqual("partial", result["status"])
        self.assertEqual(["Garmin-Erholungswerte"], result["incomplete_sources"])
        self.assertEqual({"Garmin-Erholungswerte": "partial"}, result["source_status"])

    def test_a_failed_garmin_read_is_reported_as_not_refreshed(self):
        service, garmin = self.make_service()
        garmin.refresh.side_effect = RuntimeError("provider failure")

        result = service.refresh("load")

        self.assertEqual("failed", result["status"])
        self.assertEqual(["Garmin-Belastungswerte"], result["not_refreshed_sources"])
        self.assertEqual([], result["refreshed_sources"])

    def test_a_garmin_result_without_any_source_is_not_reported_as_refreshed(self):
        service, garmin = self.make_service()
        garmin.refresh.return_value = {"status": "ok", "sources": {"activities": False}}

        result = service.refresh("performance")

        self.assertEqual("failed", result["status"])
        self.assertEqual([], result["refreshed_sources"])

    def test_a_running_garmin_sync_is_pending(self):
        service, garmin = self.make_service()
        garmin.refresh.return_value = {"status": "already_running"}

        result = service.refresh("load")

        self.assertEqual("already_running", result["status"])
        self.assertEqual(["Garmin-Belastungswerte"], result["pending_sources"])

    def test_invalid_area_and_period_are_rejected(self):
        service, _garmin = self.make_service()

        with self.assertRaises(AppError):
            service.refresh("unknown")
        with self.assertRaises(AppError):
            service.refresh("sessions", days=84)
        with self.assertRaises(AppError):
            service.refresh("load", days=30)


if __name__ == "__main__":
    unittest.main()
