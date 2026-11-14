"""The diagnostics builder reads the live owners from the context (#2099)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.coach.service import command_receipt
from backend.diagnostics import wiring as diagnostics_wiring


class DiagnosticsBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.ctx.log_path = Mock(return_value=Path("temporary-test.log"))
        self.ctx.app_name = "Pacecraft · AI Coach"
        self.ctx.app_version = "test"
        self.ctx.coach_dialogue_tools = ({"name": "read_profile"},)
        self.services = diagnostics_wiring.build_diagnostics(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.config.assert_not_called()
        self.ctx.garmin.projection_service.assert_not_called()
        self.ctx.log_path.assert_not_called()

    def test_report_uses_current_shared_owners(self) -> None:
        ctx = self.ctx
        with patch.object(diagnostics_wiring, "DiagnosticReportService") as service:
            self.services.report_service()

        deps = service.call_args.args[0]
        self.assertIs(deps.database_manager, ctx.database.return_value)
        self.assertIs(deps.key_values, ctx.key_values)
        self.assertIs(deps.config, ctx.config.return_value)
        self.assertIs(deps.settings, ctx.settings)
        self.assertEqual((deps.app_name, deps.app_version), (ctx.app_name, "test"))
        self.assertIs(deps.redactor, ctx.redactor)
        self.assertIs(deps.diagnostic_capture, ctx.diagnostic_capture)
        self.assertIs(deps.provider_state, ctx.provider_state.return_value)
        self.assertIs(
            deps.provider_freshness, ctx.provider_sync.freshness_service.return_value
        )
        self.assertIs(deps.profile, ctx.athlete.profile.return_value)
        garmin = ctx.garmin
        self.assertIs(deps.garmin_projection, garmin.projection_service.return_value)
        self.assertIs(deps.garmin_client_factory, garmin.client_factory.return_value)
        self.assertIs(deps.garmin_fixture_loader, garmin.fixture_loader.return_value)
        self.assertIs(deps.garmin_sync_state, garmin.sync_state_service.return_value)
        self.assertIs(
            deps.external_calendar_sync,
            ctx.external_calendar.sync_service.return_value,
        )
        self.assertIs(
            deps.external_calendar_reader, ctx.external_calendar.reader.return_value
        )
        self.assertIs(
            deps.morning_checkin,
            ctx.coach_local.morning_checkin_state_service.return_value,
        )
        self.assertIs(
            deps.workout_library_sync_state,
            ctx.workout_library_sync.sync_state_service.return_value,
        )
        self.assertIs(deps.canonical_coverage, ctx.canonical_read)
        self.assertIs(deps.canonical_read, ctx.canonical_read)
        self.assertIs(deps.canonical_backfill, ctx.canonical_backfill.status_reader)
        self.assertEqual(deps.coach_history._allowed_tools, frozenset({"read_profile"}))

    def test_the_change_check_status_is_read_when_the_report_asks(self) -> None:
        with patch.object(diagnostics_wiring, "DiagnosticReportService") as service:
            self.services.report_service()
        change_check = service.call_args.args[0].garmin_change_check
        self.ctx.garmin.change_check.assert_not_called()

        self.assertIs(change_check(), self.ctx.garmin.change_check().status())

    def test_the_lt1_ride_coverage_is_counted_when_the_report_asks(self) -> None:
        with patch.object(diagnostics_wiring, "DiagnosticReportService") as service:
            self.services.report_service()
        coverage = service.call_args.args[0].lt1_ride_coverage
        reports = self.ctx.performance.training_reports
        reports.assert_not_called()

        with patch.object(diagnostics_wiring, "ride_band_coverage") as count:
            self.assertIs(coverage(), count.return_value)
        records = reports.return_value.profiles.curve_records
        records.assert_called_once_with(60)
        count.assert_called_once_with(
            records.return_value, self.ctx.clock.now.return_value.date.return_value
        )

    def test_services_are_fresh_and_log_reader_keeps_shared_redactor(self) -> None:
        first = self.services.recent_log_entries_service()
        second = self.services.recent_log_entries_service()
        self.assertIsNot(first, second)
        self.assertIs(first._redactor, self.ctx.redactor)
        self.assertEqual(first._log_path, Path("temporary-test.log"))

        first_history = self.services.coach_history_service()
        second_history = self.services.coach_history_service()
        self.assertIsNot(first_history, second_history)

    def test_the_log_path_follows_the_live_value(self) -> None:
        self.ctx.log_path.return_value = Path("restored.log")

        self.assertEqual(
            self.services.recent_log_entries_service()._log_path, Path("restored.log")
        )

    def test_positional_and_keyword_arguments_keep_their_places(self) -> None:
        with patch.object(diagnostics_wiring, "RecentLogEntriesService") as logs:
            self.services.recent_log_entries_service()
        path, redactor, utc_now = logs.call_args.args
        self.assertEqual(path, Path("temporary-test.log"))
        self.assertIs(redactor, self.ctx.redactor)
        self.assertTrue(callable(utc_now))

        with patch.object(
            diagnostics_wiring, "CoachDiagnosticHistoryService"
        ) as history:
            self.services.coach_history_service()
        kwargs = history.call_args.kwargs
        self.assertIs(kwargs["database"], self.ctx.database.return_value.read_snapshot)
        self.assertIs(kwargs["redact"], self.ctx.redactor.sanitize_diagnostic_value)
        self.assertIs(kwargs["receipt_parser"], command_receipt)
        self.assertEqual(list(kwargs["allowed_tools"]), ["read_profile"])


if __name__ == "__main__":
    unittest.main()
