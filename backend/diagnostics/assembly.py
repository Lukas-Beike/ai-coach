"""Composition for local, privacy-safe diagnostics projections."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportDependencies, DiagnosticReportService


class DiagnosticsAssembly:
    """Build fresh diagnostics projections from shared application owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        database_lock: Any,
        key_values: Any,
        config: Callable[[], Any],
        settings: Any,
        app_name: str,
        app_version: str,
        utc_now: Callable[[], Any],
        sync_state: Callable[[], Any],
        garmin_projection: Callable[[], Any],
        garmin_client_factory: Callable[[], Any],
        garmin_fixture_loader: Callable[[], Any],
        provider_state: Callable[[], Any],
        redactor: Any,
        provider_freshness: Callable[[], Any],
        profile: Callable[[], Any],
        garmin_sync_state: Callable[[], Any],
        external_calendar_sync: Callable[[], Any],
        external_calendar_reader: Callable[[], Any],
        morning_checkin: Callable[[], Any],
        workout_library_sync_state: Callable[[], Any],
        diagnostic_capture: Any,
        log_path: Callable[[], Path],
        receipt_parser: Callable[[Any], Any],
        allowed_tools: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._config = config
        self._settings = settings
        self._app_name = app_name
        self._app_version = app_version
        self._utc_now = utc_now
        self._sync_state = sync_state
        self._garmin_projection = garmin_projection
        self._garmin_client_factory = garmin_client_factory
        self._garmin_fixture_loader = garmin_fixture_loader
        self._provider_state = provider_state
        self._redactor = redactor
        self._provider_freshness = provider_freshness
        self._profile = profile
        self._garmin_sync_state = garmin_sync_state
        self._external_calendar_sync = external_calendar_sync
        self._external_calendar_reader = external_calendar_reader
        self._morning_checkin = morning_checkin
        self._workout_library_sync_state = workout_library_sync_state
        self._diagnostic_capture = diagnostic_capture
        self._log_path = log_path
        self._receipt_parser = receipt_parser
        self._allowed_tools = allowed_tools

    def recent_log_entries_service(self) -> RecentLogEntriesService:
        return RecentLogEntriesService(self._log_path(), self._redactor, self._utc_now)

    def coach_history_service(self) -> CoachDiagnosticHistoryService:
        return CoachDiagnosticHistoryService(
            database=self._database_manager().unit_of_work,
            db_lock=self._database_lock,
            redact=self._redactor.sanitize_log_value,
            receipt_parser=self._receipt_parser,
            allowed_tools=self._allowed_tools(),
        )

    def report_service(self) -> DiagnosticReportService:
        return DiagnosticReportService(DiagnosticReportDependencies(
            database_manager=self._database_manager(),
            db_lock=self._database_lock,
            key_values=self._key_values,
            config=self._config(),
            settings=self._settings,
            app_name=self._app_name,
            app_version=self._app_version,
            utc_now=self._utc_now,
            sync_state=self._sync_state(),
            garmin_projection=self._garmin_projection(),
            garmin_client_factory=self._garmin_client_factory(),
            garmin_fixture_loader=self._garmin_fixture_loader(),
            provider_state=self._provider_state(),
            coach_history=self.coach_history_service(),
            redactor=self._redactor,
            provider_freshness=self._provider_freshness(),
            profile=self._profile(),
            garmin_sync_state=self._garmin_sync_state(),
            external_calendar_sync=self._external_calendar_sync(),
            external_calendar_reader=self._external_calendar_reader(),
            morning_checkin=self._morning_checkin(),
            workout_library_sync_state=self._workout_library_sync_state(),
            recent_logs=self.recent_log_entries_service(),
            diagnostic_capture=self._diagnostic_capture,
        ))
