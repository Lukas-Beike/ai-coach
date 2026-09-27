"""Composition for local, privacy-safe diagnostics projections."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportDependencies, DiagnosticReportService


@dataclass(frozen=True)
class DiagnosticRuntimeDependencies:
    database_manager: Callable[[], Any]
    database_lock: Any
    key_values: Any
    config: Callable[[], Any]
    settings: Any
    app_name: str
    app_version: str


@dataclass(frozen=True)
class DiagnosticProviderHealth:
    sync_state: Callable[[], Any]
    provider_state: Callable[[], Any]
    provider_freshness: Callable[[], Any]
    redactor: Any


@dataclass(frozen=True)
class DiagnosticGarminServices:
    projection: Callable[[], Any]
    client_factory: Callable[[], Any]
    fixture_loader: Callable[[], Any]
    sync_state: Callable[[], Any]


@dataclass(frozen=True)
class DiagnosticLocalProjections:
    profile: Callable[[], Any]
    external_calendar_sync: Callable[[], Any]
    external_calendar_reader: Callable[[], Any]
    morning_checkin: Callable[[], Any]
    workout_library_sync_state: Callable[[], Any]


@dataclass(frozen=True)
class DiagnosticReportSettings:
    utc_now: Callable[[], Any]
    diagnostic_capture: Any
    log_path: Callable[[], Path]
    receipt_parser: Callable[[Any], Any]
    allowed_tools: Callable[[], Any]


class DiagnosticsAssembly:
    """Build fresh diagnostics projections from shared application owners."""

    @dataclass(frozen=True)
    class Inputs:
        runtime: DiagnosticRuntimeDependencies
        provider_health: DiagnosticProviderHealth
        garmin: DiagnosticGarminServices
        local_projections: DiagnosticLocalProjections
        report: DiagnosticReportSettings

    def __init__(self, *, dependencies: "DiagnosticsAssembly.Inputs") -> None:
        runtime = dependencies.runtime
        provider = dependencies.provider_health
        garmin = dependencies.garmin
        local = dependencies.local_projections
        report = dependencies.report
        self._database_manager = runtime.database_manager
        self._database_lock = runtime.database_lock
        self._key_values = runtime.key_values
        self._config = runtime.config
        self._settings = runtime.settings
        self._app_name = runtime.app_name
        self._app_version = runtime.app_version
        self._utc_now = report.utc_now
        self._sync_state = provider.sync_state
        self._provider_state = provider.provider_state
        self._provider_freshness = provider.provider_freshness
        self._redactor = provider.redactor
        self._garmin_projection = garmin.projection
        self._garmin_client_factory = garmin.client_factory
        self._garmin_fixture_loader = garmin.fixture_loader
        self._garmin_sync_state = garmin.sync_state
        self._profile = local.profile
        self._external_calendar_sync = local.external_calendar_sync
        self._external_calendar_reader = local.external_calendar_reader
        self._morning_checkin = local.morning_checkin
        self._workout_library_sync_state = local.workout_library_sync_state
        self._diagnostic_capture = report.diagnostic_capture
        self._log_path = report.log_path
        self._receipt_parser = report.receipt_parser
        self._allowed_tools = report.allowed_tools

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
