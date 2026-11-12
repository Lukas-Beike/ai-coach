"""Built-in provider bindings and the runtime registry assembled from them.

Each built-in provider contributes one ``ProviderRuntimeBinding`` built from the
live owners in ``ProviderRuntimeDependencies``. ``build_provider_runtime``
validates the bindings against a static registry and returns the view that the
assemblies read when they receive a ``provider_runtime`` callable.

Contract for the callable: it must return a fresh registry for each assembly
build. Schedule policies snapshot their configuration when first resolved, and a
registry caches what it resolves, so a reused registry would keep a stale
snapshot. Bindings name providers only through the descriptor constants.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from backend.athlete.profile import ProfileService
from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.sync.commands import GarminSynchronousRefresh, WahooSynchronousRefresh
from backend.sync.execution_assembly import (
    CalendarWeatherJobDependencies,
    GarminJobDependencies,
    HistoricalSyncDependencies,
    IntervalsJobDependencies,
    SyncJobStateDependencies,
    WahooJobDependencies,
)
from backend.sync.freshness_sources import DEFAULT_FRESHNESS_SOURCES
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.provider_resync_assembly import GarminFullResync, WahooFullResync
from backend.sync.provider_runtime import (
    ProviderRuntimeBinding,
    ProviderRuntimeRegistry,
)
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.schedule_policies import (
    CalendarSchedulePolicy,
    GarminSchedulePolicy,
    WahooSchedulePolicy,
    WeatherSchedulePolicy,
)


@dataclass(frozen=True)
class ProviderRuntimeDependencies:
    """Live owners the built-in bindings resolve only when the registry asks."""

    config: Callable[[], Config]
    profile: Callable[[], ProfileService]
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    database_lock: Any
    garmin_resync_gate: ProviderResyncGate
    garmin_automatic_sync_days: int
    historical: HistoricalSyncDependencies
    state: SyncJobStateDependencies
    intervals: IntervalsJobDependencies
    garmin: GarminJobDependencies
    calendar_weather: CalendarWeatherJobDependencies
    wahoo: WahooJobDependencies


def intervals_binding(deps: ProviderRuntimeDependencies) -> ProviderRuntimeBinding:
    """Bind the Intervals.icu output target's configured check and freshness."""
    return ProviderRuntimeBinding(
        provider_id=INTERVALS_ID,
        configured=lambda: bool(deps.config().intervals_api_key),
        gate=deps.intervals.resync_gate,
        freshness=DEFAULT_FRESHNESS_SOURCES[INTERVALS_ID],
    )


def garmin_binding(deps: ProviderRuntimeDependencies) -> ProviderRuntimeBinding:
    """Bind the Garmin automatic schedule, full resync and Coach refresh."""
    garmin = deps.garmin
    all_sync_days = deps.historical.all_sync_days

    def schedule() -> GarminSchedulePolicy:
        return GarminSchedulePolicy(
            garmin.sync_service(),
            deps.garmin_automatic_sync_days,
            deps.garmin_resync_gate,
            None if garmin.change_check is None else garmin.change_check(),
        )

    def full_resync() -> GarminFullResync:
        return GarminFullResync(
            garmin_service=garmin.sync_service(), all_sync_days=all_sync_days
        )

    def synchronous_refresh() -> GarminSynchronousRefresh:
        return GarminSynchronousRefresh(
            garmin.sync_service(),
            garmin.morning_body_battery_service(),
            all_sync_days,
        )

    return ProviderRuntimeBinding(
        provider_id=GARMIN_ID,
        configured=lambda: bool(garmin.sync_service().configured()),
        gate=deps.garmin_resync_gate,
        schedule=schedule,
        freshness=DEFAULT_FRESHNESS_SOURCES[GARMIN_ID],
        full_resync=full_resync,
        synchronous_refresh=synchronous_refresh,
    )


def wahoo_binding(deps: ProviderRuntimeDependencies) -> ProviderRuntimeBinding:
    """Bind the Wahoo workout sync, scheduled once the athlete connected."""
    wahoo = deps.wahoo
    all_sync_days = deps.historical.all_sync_days

    def schedule() -> WahooSchedulePolicy:
        return WahooSchedulePolicy(
            configured=lambda: wahoo.sync_service().configured(),
            sync_state=deps.state.sync_state_repository(),
            sync_period_defaults=deps.historical.sync_period_defaults,
            all_sync_days=all_sync_days,
            resync_gate=wahoo.resync_gate,
        )

    def full_resync() -> WahooFullResync:
        return WahooFullResync(
            sync_service=wahoo.sync_service(), all_sync_days=all_sync_days
        )

    def synchronous_refresh() -> WahooSynchronousRefresh:
        state = deps.state.sync_state_repository()
        return WahooSynchronousRefresh(
            wahoo.sync_service(),
            all_sync_days,
            stored_days=lambda: state.sync_period(
                WAHOO_ID, deps.historical.sync_period_defaults, all_sync_days
            ),
        )

    return ProviderRuntimeBinding(
        provider_id=WAHOO_ID,
        configured=lambda: wahoo.sync_service().configured(),
        gate=wahoo.resync_gate,
        schedule=schedule,
        freshness=DEFAULT_FRESHNESS_SOURCES[WAHOO_ID],
        full_resync=full_resync,
        synchronous_refresh=synchronous_refresh,
        running_probe=lambda: wahoo.sync_service().running(),
    )


def weather_binding(deps: ProviderRuntimeDependencies) -> ProviderRuntimeBinding:
    """Bind the weather forecast's location-driven schedule."""

    def schedule() -> WeatherSchedulePolicy:
        return WeatherSchedulePolicy(
            deps.profile(),
            refresh_due=lambda: (
                deps.calendar_weather.weather_sync_service().refresh_due()
            ),
        )

    return ProviderRuntimeBinding(
        provider_id=WEATHER_ID,
        configured=lambda: schedule().configured(),
        schedule=schedule,
        freshness=DEFAULT_FRESHNESS_SOURCES[WEATHER_ID],
    )


def calendar_binding(deps: ProviderRuntimeDependencies) -> ProviderRuntimeBinding:
    """Bind the external calendar's configured-URL schedule."""

    def schedule() -> CalendarSchedulePolicy:
        return CalendarSchedulePolicy(enabled=bool(deps.config().calendar_ical_url))

    return ProviderRuntimeBinding(
        provider_id=CALENDAR_ID,
        configured=lambda: schedule().configured(),
        schedule=schedule,
        freshness=DEFAULT_FRESHNESS_SOURCES[CALENDAR_ID],
    )


def builtin_bindings(
    deps: ProviderRuntimeDependencies,
) -> tuple[ProviderRuntimeBinding, ...]:
    """Return the bindings of the five built-in providers."""
    return (
        intervals_binding(deps),
        garmin_binding(deps),
        wahoo_binding(deps),
        weather_binding(deps),
        calendar_binding(deps),
    )


def build_provider_runtime(
    static: ProviderRegistry, bindings: Iterable[ProviderRuntimeBinding]
) -> ProviderRuntimeRegistry:
    """Validate bindings against the static registry and return the runtime view.

    Every descriptor needs a binding here, so a provider cannot silently drop out
    of scheduling, execution or status.
    """
    bound = tuple(bindings)
    if set(static.ids()) - {binding.provider_id for binding in bound}:
        raise ValueError("provider descriptor has no runtime binding")
    return ProviderRuntimeRegistry(static, bound)
