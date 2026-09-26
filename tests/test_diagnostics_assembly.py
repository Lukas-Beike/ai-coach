"""Tests for the diagnostics composition boundary."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.diagnostics.assembly import DiagnosticsAssembly


class DiagnosticsAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.deps = {
            "database_manager": Mock(return_value=Mock(unit_of_work=Mock())),
            "database_lock": Mock(),
            "key_values": Mock(),
            "config": Mock(return_value=Mock()),
            "settings": Mock(),
            "app_name": "Intervals Coach",
            "app_version": "test",
            "utc_now": Mock(),
            "sync_state": Mock(),
            "garmin_projection": Mock(),
            "garmin_client_factory": Mock(),
            "garmin_fixture_loader": Mock(),
            "provider_state": Mock(),
            "redactor": Mock(),
            "provider_freshness": Mock(),
            "profile": Mock(),
            "garmin_sync_state": Mock(),
            "external_calendar_sync": Mock(),
            "external_calendar_reader": Mock(),
            "morning_checkin": Mock(),
            "workout_library_sync_state": Mock(),
            "diagnostic_capture": Mock(),
            "log_path": Mock(return_value=Path("temporary-test.log")),
            "receipt_parser": Mock(return_value={}),
            "allowed_tools": Mock(return_value=["read_profile"]),
        }
        self.assembly = DiagnosticsAssembly(**self.deps)

    def test_report_uses_current_shared_owners(self):
        with patch("backend.diagnostics.assembly.DiagnosticReportService") as service:
            self.assembly.report_service()

        dependencies = service.call_args.args[0]
        self.assertIs(dependencies.database_manager, self.deps["database_manager"].return_value)
        self.assertIs(dependencies.key_values, self.deps["key_values"])
        self.assertIs(dependencies.redactor, self.deps["redactor"])
        self.assertIs(dependencies.diagnostic_capture, self.deps["diagnostic_capture"])
        self.assertEqual(dependencies.coach_history._allowed_tools, frozenset({"read_profile"}))

    def test_services_are_fresh_and_log_reader_keeps_shared_redactor(self):
        first = self.assembly.recent_log_entries_service()
        second = self.assembly.recent_log_entries_service()
        self.assertIsNot(first, second)
        self.assertIs(first._redactor, self.deps["redactor"])
        self.assertEqual(first._log_path, self.deps["log_path"].return_value)

        first_history = self.assembly.coach_history_service()
        second_history = self.assembly.coach_history_service()
        self.assertIsNot(first_history, second_history)
        self.assertIs(first_history._db_lock, self.deps["database_lock"])


if __name__ == "__main__":
    unittest.main()
