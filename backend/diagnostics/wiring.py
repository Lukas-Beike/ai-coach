"""Build the local, privacy-safe diagnostics projections from the application context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from backend.app.context import AppContext
from backend.coach.service import command_receipt
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.performance.decoupling_eligibility import DecouplingEligibility
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.pace_at_hr import LT1_DAYS, ride_band_coverage
from backend.runtime import clock as runtime_clock
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_metrics import analysis_activity


@dataclass(frozen=True)
class DiagnosticsServices:
    recent_log_entries_service: Callable[[], RecentLogEntriesService]
    coach_history_service: Callable[[], CoachDiagnosticHistoryService]
    report_service: Callable[[], DiagnosticReportService]


def build_diagnostics(ctx: AppContext) -> DiagnosticsServices:
    """Fresh projections per call over the current database and domain owners."""
    utc_now = runtime_clock.utc_now
    # Lives with the process: its background slot keeps the last report (#2779).
    sessions = CanonicalTableReader()
    decoupling = DecouplingEligibility(
        ctx.database,
        sessions.activity_sessions,
        analysis_activity,
        ctx.key_values,
        lambda: ctx.clock.now().date(),
        SessionCurveReader(
            sessions.session_activities, background_name="decoupling_eligibility"
        ),
    )

    def recent_log_entries_service() -> RecentLogEntriesService:
        return RecentLogEntriesService(ctx.log_path(), ctx.redactor, utc_now)

    def coach_history_service() -> CoachDiagnosticHistoryService:
        return CoachDiagnosticHistoryService(
            database=ctx.database().read_snapshot,
            redact=ctx.redactor.sanitize_diagnostic_value,
            receipt_parser=command_receipt,
            allowed_tools=tuple(tool["name"] for tool in ctx.coach_dialogue_tools),
        )

    def report_service() -> DiagnosticReportService:
        garmin = ctx.garmin
        return DiagnosticReportService(
            DiagnosticReportDependencies(
                database_manager=ctx.database(),
                key_values=ctx.key_values,
                config=ctx.config(),
                settings=ctx.settings,
                app_name=ctx.app_name,
                app_version=ctx.app_version,
                utc_now=utc_now,
                garmin_projection=garmin.projection_service(),
                garmin_client_factory=garmin.client_factory(),
                garmin_fixture_loader=garmin.fixture_loader(),
                provider_state=ctx.provider_state(),
                coach_history=coach_history_service(),
                redactor=ctx.redactor,
                provider_freshness=ctx.provider_sync.freshness_service(),
                profile=ctx.athlete.profile(),
                garmin_sync_state=garmin.sync_state_service(),
                external_calendar_sync=ctx.external_calendar.sync_service(),
                external_calendar_reader=ctx.external_calendar.reader(),
                morning_checkin=ctx.coach_local.morning_checkin_state_service(),
                workout_library_sync_state=ctx.workout_library_sync.sync_state_service(),
                canonical_coverage=ctx.canonical_read,
                recent_logs=recent_log_entries_service(),
                diagnostic_capture=ctx.diagnostic_capture,
                canonical_backfill=ctx.canonical_backfill.status_reader,
                canonical_read=ctx.canonical_read,
                # The Garmin change check's status: counts and times only (#2372).
                garmin_change_check=lambda: garmin.change_check().status(),
                lt1_ride_coverage=lambda: ride_band_coverage(
                    ctx.performance.training_reports().profiles.curve_records(LT1_DAYS),
                    ctx.clock.now().date(),
                ),
                decoupling_eligibility=decoupling.section,
                database_path=ctx.database_path,
                curve_build=ctx.performance.curve_build_state,
            )
        )

    return DiagnosticsServices(
        recent_log_entries_service, coach_history_service, report_service
    )
