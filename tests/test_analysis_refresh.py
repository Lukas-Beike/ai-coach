import unittest
from datetime import date
from unittest.mock import Mock

from backend.sync.analysis_refresh import AnalysisRefreshService


class AnalysisRefreshTests(unittest.TestCase):
    def make_service(self, today=date(2026, 10, 20)):
        intervals = Mock()
        intervals.refresh.return_value = {"status": "ok"}
        sessions = Mock()
        sessions.refresh.return_value = {
            "status": "partial",
            "reconciliation_pending": True,
        }
        garmin = Mock()
        garmin.refresh.return_value = {
            "status": "ok",
            "sources": {"activities": True},
        }
        service = AnalysisRefreshService(
            lambda: intervals, lambda: sessions, lambda: garmin, lambda: today
        )
        return service, intervals, sessions, garmin

    def test_sessions_refreshes_only_bounded_activity_sources(self):
        service, intervals, sessions, garmin = self.make_service()

        result = service.refresh("sessions")

        intervals.refresh.assert_not_called()
        sessions.refresh.assert_called_once_with()
        garmin.refresh.assert_called_once_with(
            "sessions", date(2026, 9, 9), date(2026, 10, 20)
        )
        self.assertEqual("partial", result["status"])
        self.assertEqual(
            ["Intervals.icu-Aktivitätsübersicht"], result["incomplete_sources"]
        )
        self.assertEqual(2, len(result["refreshed_sources"]))

    def test_recovery_refreshes_its_own_garmin_area_and_reports_partial_sources(self):
        service, intervals, sessions, garmin = self.make_service()
        garmin.refresh.return_value = {
            "status": "partial",
            "sources": {"sleep": True, "hrv": False},
        }

        result = service.refresh("recovery", days=84)

        intervals.refresh.assert_called_once_with(include_power_profile=False)
        sessions.refresh.assert_not_called()
        garmin.refresh.assert_called_once_with(
            "recovery", date(2026, 7, 29), date(2026, 10, 20)
        )
        self.assertEqual("partial", result["status"])
        self.assertEqual(["Garmin-Erholungswerte"], result["incomplete_sources"])

    def test_failed_provider_does_not_discard_other_fresh_results(self):
        service, intervals, _sessions, garmin = self.make_service()
        intervals.refresh.side_effect = RuntimeError("synthetic provider failure")

        result = service.refresh("load")

        self.assertEqual("partial", result["status"])
        self.assertEqual(["Garmin-Belastungswerte"], result["refreshed_sources"])
        self.assertEqual(
            ["Intervals.icu-Belastungsdaten"], result["not_refreshed_sources"]
        )
        garmin.refresh.assert_called_once()

    def test_performance_includes_power_profile(self):
        service, intervals, sessions, garmin = self.make_service()

        result = service.refresh("performance")

        intervals.refresh.assert_called_once_with(include_power_profile=True)
        sessions.refresh.assert_not_called()
        garmin.refresh.assert_called_once_with(
            "performance", date(2026, 7, 23), date(2026, 10, 20)
        )
        self.assertEqual("ok", result["status"])

    def test_truncated_intervals_result_is_incomplete_without_partial_status(self):
        service, intervals, _sessions, _garmin = self.make_service()
        intervals.refresh.return_value = {"status": "ok", "truncated": True}

        result = service.refresh("load")

        self.assertEqual("partial", result["status"])
        self.assertEqual(
            ["Intervals.icu-Belastungsdaten"], result["incomplete_sources"]
        )
        self.assertEqual(["Intervals.icu-Belastungsdaten"], result["truncated_sources"])

    def test_no_garmin_source_is_not_reported_as_refreshed(self):
        service, _intervals, _sessions, garmin = self.make_service()
        garmin.refresh.return_value = {
            "status": "partial",
            "sources": {"sleep": False},
        }

        result = service.refresh("recovery")

        self.assertEqual(["Intervals.icu-Erholungsdaten"], result["refreshed_sources"])
        self.assertEqual(["Garmin-Erholungswerte"], result["not_refreshed_sources"])


if __name__ == "__main__":
    unittest.main()
