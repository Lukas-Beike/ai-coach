"""The real composition root resolves every service of the builder domains (#2069).

It replaces the mock-identity assembly tests: server.py builds the application
context and calls the domain builders on a temporary database, and each
service is resolved through the real wiring. Each builder step adds its
domain here.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from server_test_support import ServerTestCase, server

from backend.backup.database import DatabaseBackupService
from backend.backup.export import PrivacyArchiveExportService
from backend.backup.restore import DatabaseRestoreService
from backend.backup.restore_validation import DatabaseRestoreValidationService
from backend.coach.job_store import CoachJobStore
from backend.coach.turn_failures import CoachTurnFailureService
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.nutrition.catalog import ProductCatalogService
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.privacy import PrivacyDeleteService
from backend.providers import audio as audio_provider
from backend.providers.claude_models import ClaudeModelResolver
from backend.providers.claude_requests import ClaudeMessagesClient
from backend.providers.http import JsonHttpClient
from backend.providers.intervals_client import IntervalsClient
from backend.providers.openai_requests import OpenAIResponsesClient
from backend.providers.openai_stream import OpenAIStreamClient
from backend.sync.queue import SyncJobQueueService
from backend.sync.weather import WeatherSyncService
from backend.weather.service import WeatherService


class CompositionRootTests(ServerTestCase):
    def test_history_services_resolve_over_the_current_database(self) -> None:
        history = server.HISTORY

        self.assertIsInstance(history.change_history_service(), ChangeHistoryService)
        self.assertIsInstance(history.undo_service(), HistoryUndoService)

    def test_weather_services_resolve(self) -> None:
        self.assertIsInstance(server.WEATHER.service(), WeatherService)
        self.assertIsInstance(server.WEATHER_SYNC(), WeatherSyncService)

    def test_nutrition_services_resolve(self) -> None:
        nutrition = server.NUTRITION_SERVICES

        self.assertIsInstance(nutrition.diary_service(), NutritionDiaryService)
        self.assertIsInstance(
            nutrition.meal_library_service(), NutritionMealLibraryService
        )
        self.assertIsInstance(
            nutrition.product_catalog_service(), ProductCatalogService
        )
        self.assertIsInstance(
            nutrition.intervals_sync_service(), IntervalsNutritionSyncService
        )
        self.assertIs(nutrition.food_mirror(), nutrition.food_mirror())

    def test_backup_services_resolve_over_the_live_owners(self) -> None:
        backup = server.BACKUP

        self.assertIsInstance(backup.backup_service(), DatabaseBackupService)
        self.assertIsInstance(
            backup.restore_validation_service(), DatabaseRestoreValidationService
        )
        restore = backup.restore_service()
        self.assertIsInstance(restore, DatabaseRestoreService)
        self.assertEqual(restore._dependencies.config.database_path, server.DB_PATH)
        self.assertEqual(restore._dependencies.config.data_dir, server.DATA_DIR)
        self.assertIsInstance(restore._dependencies.sync_jobs, SyncJobQueueService)
        self.assertIsInstance(restore._dependencies.coach_jobs, CoachJobStore)
        self.assertIsInstance(
            restore._dependencies.coach_failures, CoachTurnFailureService
        )

    def test_privacy_services_resolve_without_exporting_or_purging(self) -> None:
        privacy = server.PRIVACY

        export = privacy.archive_export_service()
        self.assertIsInstance(export, PrivacyArchiveExportService)
        self.assertEqual(export._config.data_dir, server.DATA_DIR)
        self.assertEqual(export._config.database_path, server.DB_PATH)
        purge = privacy.delete_service()
        self.assertIsInstance(purge, PrivacyDeleteService)
        dependencies = purge._dependencies
        self.assertIs(dependencies.database_lock, server.DB_LOCK)
        self.assertIs(
            dependencies.maintenance_gate, server.runtime_maintenance.MAINTENANCE_GATE
        )
        self.assertIsInstance(dependencies.log_files, RecentLogEntriesService)
        assert dependencies.recovery_copies is not None
        self.assertEqual(dependencies.recovery_copies._data_dir, server.DATA_DIR)
        for late in (
            dependencies.refresh_credentials,
            dependencies.cancel_garmin_login,
            dependencies.disconnect_wahoo,
            dependencies.cancel_coach_turns,
        ):
            self.assertTrue(callable(late))
        with dependencies.diagnostics_suspended():
            pass

    def test_diagnostics_services_resolve_over_the_live_owners(self) -> None:
        diagnostics = server.DIAGNOSTICS

        logs = diagnostics.recent_log_entries_service()
        self.assertIsInstance(logs, RecentLogEntriesService)
        self.assertEqual(logs._log_path, server.LOG_PATH)
        self.assertIsInstance(
            diagnostics.coach_history_service(), CoachDiagnosticHistoryService
        )
        report = diagnostics.report_service()
        self.assertIsInstance(report, DiagnosticReportService)
        self.assertIn("logs", report.report())

    def test_provider_transports_build_their_clients_over_the_live_owners(
        self,
    ) -> None:
        # Only constructs clients; no remote endpoint is called.
        provider = server.PROVIDER_TRANSPORT
        http_client = provider.json_http_client()
        self.assertIsInstance(http_client, JsonHttpClient)
        self.assertIs(provider.json_http_client(), http_client)
        self.assertIs(server.APP.provider_transport, provider)
        self.assertIsInstance(provider.intervals_client(), IntervalsClient)
        explicit = replace(server.CONFIG, intervals_api_key="test-key")
        self.assertIs(provider.intervals_client(explicit).config, explicit)

        model = server.MODEL_TRANSPORT
        self.assertIs(server.APP.model_transport, model)
        self.assertIsInstance(model.openai_responses_client(), OpenAIResponsesClient)
        self.assertIsInstance(model.openai_stream_client(), OpenAIStreamClient)
        self.assertIsInstance(model.claude_client(), ClaudeMessagesClient)
        self.assertIsInstance(
            model.audio_transcription_client(), audio_provider.AudioTranscriptionClient
        )
        self.assertIsInstance(model.claude_models(), ClaudeModelResolver)
        self.assertEqual(
            model.openai_stream_client().config.timeout,
            server.OPENAI_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertTrue(callable(model.complete) and callable(model.stream))

    def test_the_redactor_reads_the_nutrition_secrets(self) -> None:
        # The log redactor looks the nutrition services up by name.
        services = SimpleNamespace(secret_values=lambda: ("yazio-token",))
        with patch.object(server, "NUTRITION_SERVICES", services):
            self.assertIn("yazio-token", server._nutrition_secret_values())

    def test_the_context_reads_the_live_configuration_and_database(self) -> None:
        replaced = replace(server.CONFIG, calendar_ical_url="https://example.invalid")
        with patch.object(server, "CONFIG", replaced):
            self.assertIs(replaced, server.APP.config())
        self.assertIs(server.database_manager(), server.APP.database())


if __name__ == "__main__":
    unittest.main()
