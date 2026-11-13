import unittest
from datetime import date
from unittest.mock import Mock

from backend.errors import AppError
from backend.sync.analysis_refresh import AnalysisRefreshService


class AnalysisRefreshTests(unittest.TestCase):
    def make_service(self, today=date(2026, 10, 20)):
        garmin = Mock()
        garmin.refresh_analysis.return_value = {
            "status": "ok",
            "sources": {"activities": True},
        }
        return AnalysisRefreshService(lambda: garmin, lambda: today), garmin

    def test_sessions_refresh_the_bounded_garmin_activity_window(self):
        service, garmin = self.make_service()

        result = service.refresh("sessions")

        garmin.refresh_analysis.assert_called_once_with(
            "sessions", date(2026, 9, 9), date(2026, 10, 20)
        )
        self.assertEqual("ok", result["status"])
        self.assertEqual(["Garmin-Aktivitätsübersicht"], result["refreshed_sources"])
        self.assertEqual([], result["not_refreshed_sources"])

    def test_recovery_refreshes_its_own_garmin_area_and_reports_partial_sources(self):
        service, garmin = self.make_service()
        garmin.refresh_analysis.return_value = {
            "status": "partial",
            "sources": {"sleep": True, "hrv": False},
        }

        result = service.refresh("recovery", days=84)

        garmin.refresh_analysis.assert_called_once_with(
            "recovery", date(2026, 7, 29), date(2026, 10, 20)
        )
        self.assertEqual("partial", result["status"])
        self.assertEqual(["Garmin-Erholungswerte"], result["incomplete_sources"])
        self.assertEqual({"Garmin-Erholungswerte": "partial"}, result["source_status"])

    def test_a_failed_garmin_read_is_reported_as_not_refreshed(self):
        service, garmin = self.make_service()
        garmin.refresh_analysis.side_effect = RuntimeError("provider failure")

        result = service.refresh("load")

        self.assertEqual("failed", result["status"])
        self.assertEqual(["Garmin-Belastungswerte"], result["not_refreshed_sources"])
        self.assertEqual([], result["refreshed_sources"])

    def test_a_garmin_result_without_any_source_is_not_reported_as_refreshed(self):
        service, garmin = self.make_service()
        garmin.refresh_analysis.return_value = {"status": "ok", "sources": {"activities": False}}

        result = service.refresh("performance")

        self.assertEqual("failed", result["status"])
        self.assertEqual([], result["refreshed_sources"])

    def test_a_running_garmin_sync_is_pending(self):
        service, garmin = self.make_service()
        garmin.refresh_analysis.return_value = {"status": "already_running"}

        result = service.refresh("load")

        self.assertEqual("already_running", result["status"])
        self.assertEqual(["Garmin-Belastungswerte"], result["pending_sources"])

    def make_both(self, *, garmin_configured=True, wahoo_configured=True):
        garmin = Mock()
        garmin.refresh_analysis.return_value = (
            {"status": "ok", "sources": {"activities": True}}
            if garmin_configured
            else {"status": "partial", "reason": "not_configured"}
        )
        wahoo = Mock()
        wahoo.configured.return_value = wahoo_configured
        wahoo.sync.return_value = {"status": "ok"}
        service = AnalysisRefreshService(
            lambda: garmin, lambda: date(2026, 10, 20), lambda: wahoo
        )
        return service, garmin, wahoo

    def test_garmin_only_ignores_an_unconfigured_wahoo(self):
        service, _garmin, wahoo = self.make_both(wahoo_configured=False)

        result = service.refresh("sessions")

        wahoo.sync.assert_not_called()
        self.assertEqual("ok", result["status"])
        self.assertEqual(["Garmin-Aktivitätsübersicht"], result["refreshed_sources"])
        self.assertEqual([], result["not_refreshed_sources"])

    def test_wahoo_only_is_ok_without_a_configured_garmin(self):
        service, _garmin, wahoo = self.make_both(garmin_configured=False)

        result = service.refresh("performance")

        wahoo.sync.assert_called_once_with(90, "Analyse-Aktualisierung")
        self.assertEqual("ok", result["status"])
        self.assertEqual(["Wahoo-Leistungswerte"], result["refreshed_sources"])
        self.assertEqual([], result["not_refreshed_sources"])

    def test_both_sources_refresh_and_a_failed_wahoo_read_is_partial(self):
        service, _garmin, wahoo = self.make_both()

        result = service.refresh("sessions")

        wahoo.sync.assert_called_once_with(42, "Analyse-Aktualisierung")
        self.assertEqual("ok", result["status"])
        self.assertEqual(
            ["Garmin-Aktivitätsübersicht", "Wahoo-Aktivitätsübersicht"],
            result["refreshed_sources"],
        )
        wahoo.sync.side_effect = RuntimeError("provider failure")
        result = service.refresh("sessions")
        self.assertEqual("partial", result["status"])
        self.assertEqual(["Wahoo-Aktivitätsübersicht"], result["not_refreshed_sources"])

    def test_areas_without_wahoo_data_skip_the_wahoo_read(self):
        service, _garmin, wahoo = self.make_both()

        service.refresh("recovery")

        wahoo.sync.assert_not_called()

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
