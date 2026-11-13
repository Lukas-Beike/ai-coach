"""Build the output-flow sync services and the metric export (#2101).

Every service reads the live configuration, database and domain owners from the
application context when it is used, so a configuration change applies without a
restart. Nothing here talks to a provider by itself: each flow keeps the explicit
trigger it had (a job, a button or a named Coach request) and resolves the
Intervals.icu client only when a confirmed write needs it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from backend.app.context import AppContext
from backend.calendar.decisions import ExternalCalendarDecisionService
from backend.calendar.external import ExternalCalendarReader
from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId
from backend.performance.canonical_current import read_export_thresholds
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.current_thresholds import ThresholdKey
from backend.performance.source_policy import preferences_from_profile
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import external_calendar as external_calendar_runtime
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.intervals_metric_export import IntervalsMetricExport
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.library import (
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
)
from backend.sync.metric_export import MetricExportService
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import Capability
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.workout_export import WorkoutExportPort, WorkoutLibraryExportPort

# Intervals.icu stays the default target. A target must declare the
# workout-export capability in the provider registry; Wahoo's adapter comes from
# ``ctx.wahoo`` because it needs the Wahoo connection rather than the Intervals
# client.
DEFAULT_LIBRARY_EXPORT_TARGET = ProviderId.INTERVALS
_LIBRARY_EXPORT_TARGETS: dict[
    ProviderId, Callable[[Callable[[], Any]], WorkoutLibraryExportPort]
] = {ProviderId.INTERVALS: IntervalsWorkoutExport}


@dataclass(frozen=True)
class PlannedUnitSyncServices:
    state_writer: Callable[[], PlannedUnitSyncStateWriter]


@dataclass(frozen=True)
class PlannedCalendarSyncServices:
    sync_service: Callable[[], PlannedCalendarSyncService]
    repair_service: Callable[[], PlannedCalendarRepairService]


@dataclass(frozen=True)
class WorkoutLibrarySyncServices:
    export_port: Callable[..., WorkoutLibraryExportPort]
    sync_state_service: Callable[[], WorkoutLibrarySyncStateService]
    sync_service: Callable[[], WorkoutLibrarySyncService]


@dataclass(frozen=True)
class SelectedWorkoutSyncServices:
    service: Callable[[], SelectedWorkoutSyncService]


@dataclass(frozen=True)
class ExternalCalendarServices:
    reader: Callable[[], ExternalCalendarReader]
    sync_service: Callable[[], ExternalCalendarSyncService]
    decisions: Callable[[], ExternalCalendarDecisionService]


def _intervals_client(ctx: AppContext) -> Callable[[], Any]:
    """The Intervals.icu client lookup; the client resolves per remote call."""
    return lambda: ctx.provider_transport.intervals_client()


def build_planned_unit_sync(ctx: AppContext) -> PlannedUnitSyncServices:
    """The writer of planned-unit synchronization state over the shared revision."""

    def state_writer() -> PlannedUnitSyncStateWriter:
        return PlannedUnitSyncStateWriter(ctx.planning_revision, ctx.redactor)

    return PlannedUnitSyncServices(state_writer)


def build_planned_calendar_sync(
    ctx: AppContext,
    *,
    state_writer: Callable[[], PlannedUnitSyncStateWriter],
    future_days: int,
) -> PlannedCalendarSyncServices:
    """Normal planned-calendar sync and exact-identity repair over the live owners.

    The composition root passes the planned-unit state writer and the number of
    days ahead the repair reaches.
    """
    intervals_client = _intervals_client(ctx)

    def export_port() -> WorkoutExportPort:
        return IntervalsWorkoutExport(intervals_client)

    def run_lthr_for(unit: Mapping[str, Any]) -> float | None:
        return ctx.run_lthr.resolver()(unit)

    def today() -> date:
        return ctx.clock.now().date()

    def sync_service() -> PlannedCalendarSyncService:
        return PlannedCalendarSyncService(
            ctx.config(),
            ctx.database(),
            export_port(),
            state_writer(),
            runtime_clock.utc_now,
            today,
            run_lthr_for=run_lthr_for,
        )

    def repair_service() -> PlannedCalendarRepairService:
        return PlannedCalendarRepairService(
            ctx.database(),
            export_port(),
            state_writer(),
            runtime_clock.utc_now,
            today,
            future_days,
            run_lthr_for=run_lthr_for,
        )

    return PlannedCalendarSyncServices(sync_service, repair_service)


def build_workout_library_sync(ctx: AppContext) -> WorkoutLibrarySyncServices:
    """Independent workout-library refresh and sync use cases over the live owners."""
    intervals_client = _intervals_client(ctx)

    def export_port(
        target: ProviderId = DEFAULT_LIBRARY_EXPORT_TARGET,
    ) -> WorkoutLibraryExportPort:
        """Select the library export target; the client resolves per call."""
        port: WorkoutLibraryExportPort | None = None
        if target.value in DEFAULT_PROVIDER_REGISTRY.ids_with(
            Capability.WORKOUT_EXPORT
        ):
            if target is ProviderId.WAHOO:
                port = ctx.wahoo.workout_export()
            else:
                factory = _LIBRARY_EXPORT_TARGETS.get(target)
                port = factory(intervals_client) if factory else None
        if port is None or not port.capabilities.library:
            raise ValueError(
                f"No workout-library export target is registered: {target}"
            )
        return port

    def sync_state_service() -> WorkoutLibrarySyncStateService:
        return WorkoutLibrarySyncStateService(
            ctx.database(),
            ctx.redactor,
            ctx.key_values,
            runtime_clock.utc_now,
        )

    def sync_service() -> WorkoutLibrarySyncService:
        return WorkoutLibrarySyncService(
            ctx.config(),
            export_port(),
            sync_state_service(),
            ctx.planning_workflows.calendar_conflict_service(),
            local_today=lambda: ctx.clock.now().date(),
        )

    return WorkoutLibrarySyncServices(export_port, sync_state_service, sync_service)


def build_selected_workout_sync(
    ctx: AppContext,
    *,
    planned_calendar: PlannedCalendarSyncServices,
    resync_gate: ProviderResyncGate,
) -> SelectedWorkoutSyncServices:
    """Selected-workout sync over its three cohesive sync owners, fresh per call."""

    def service() -> SelectedWorkoutSyncService:
        return SelectedWorkoutSyncService(
            ctx.config(),
            ctx.database(),
            ctx.workout_library_sync.sync_service(),
            planned_calendar.sync_service(),
            planned_calendar.repair_service(),
            ctx.redactor.redact_text,
            provider_resync_gate=resync_gate,
        )

    return SelectedWorkoutSyncServices(service)


def build_external_calendar(ctx: AppContext) -> ExternalCalendarServices:
    """External-calendar reads and synchronization with the current config and clock."""

    def reader() -> ExternalCalendarReader:
        return ExternalCalendarReader(ctx.database(), lambda: ctx.clock.now().date())

    def sync_service() -> ExternalCalendarSyncService:
        return ExternalCalendarSyncService(
            ctx.config(),
            ctx.database(),
            ctx.key_values,
            ctx.sync_persistence.daily_markers(),
            ctx.provider_sync.operation_observer(),
            ctx.planning_workflows.adaptive_replan_preview_service(),
            runtime_events.STATE_EVENT_BUFFER,
            ctx.logger,
            ctx.redactor.redact_text,
            ctx.clock.now,
            runtime_clock.utc_now,
            ctx.app_version,
            lock=external_calendar_runtime.shared_external_calendar_sync_lock(),
        )

    def decisions() -> ExternalCalendarDecisionService:
        return ExternalCalendarDecisionService(
            ctx.database(),
            AdaptivePreviewFollowupService(
                ctx.planning_workflows.adaptive_replan_preview_service(), ctx.logger
            ),
            runtime_events.STATE_EVENT_BUFFER,
            runtime_clock.utc_now,
            lambda: ctx.clock.now().date(),
        )

    return ExternalCalendarServices(reader, sync_service, decisions)


def build_export_thresholds(
    ctx: AppContext,
) -> Callable[[Any], dict[ThresholdKey, Observation]]:
    """Return ``db -> thresholds`` an outbound export sends, current today.

    Thresholds are the resolved local, Garmin and Wahoo values. Local zones are
    read from the tables directly, like the zone editor, so a zone saved before
    the first canonical backfill completes is still sent.
    """

    def thresholds(db: Any) -> dict[ThresholdKey, Observation]:
        return read_export_thresholds(
            resolve_reader(ctx.canonical_read, db),
            db,
            as_of=ctx.clock.now().date(),
            preferences=preferences_from_profile(ctx.athlete.profile().get_from_db(db)),
            configurations=CanonicalTableReader().zone_configurations(db),
        )

    return thresholds


def build_metric_export(
    ctx: AppContext,
    *,
    thresholds: Callable[[Any], dict[ThresholdKey, Observation]],
) -> MetricExportService:
    """Return the service; a provider client is opened only by a confirmed write.

    ``thresholds`` is the shared ``build_export_thresholds`` reader.
    """
    return MetricExportService(
        ctx.database,
        lambda: ctx.canonical_read,
        {
            ProviderId.INTERVALS: lambda: IntervalsMetricExport(
                lambda: ctx.provider_transport.intervals_client()
            )
        },
        thresholds=thresholds,
        database_lock=ctx.database_lock,
        today=lambda: ctx.clock.now().date(),
        utc_now=lambda: datetime.now(UTC),
    )
