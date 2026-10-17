"""Declarative descriptors for external data providers.

The descriptors hold provider data that synchronization used to keep in literal
tables: freshness areas and labels, sync-window limits, the durable keys of
full-resync state, and the orchestration policy (job types, scheduling order,
Coach refresh targets, manual and full-resync HTTP routes). They name providers
by design, so they live in the provider package, which the provider coupling
ratchet exempts. The sync registry (backend/sync/provider_registry.py) reads
them and names no provider.

Migration is incomplete: the freshness projection still keeps its per-area
fallback sources and configured predicates in backend/sync/freshness.py, and
those must move into descriptors in a later change.

Capabilities describe what each provider can supply. They are declarative;
``ProviderRegistry.ids_with`` reads them, and the explicit library and metric
exports check that their target declares the export capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.canonical.vocabulary import MetricKind, ProviderId

INTERVALS_ID = ProviderId.INTERVALS.value
GARMIN_ID = ProviderId.GARMIN.value
WAHOO_ID = ProviderId.WAHOO.value
WEATHER_ID = "weather"
CALENDAR_ID = "calendar"

_TWO_DAYS_SECONDS = 48 * 60 * 60
_THREE_HOURS_SECONDS = 3 * 60 * 60
_INTERVALS_MAX_SYNC_DAYS = 365
DEFAULT_MAX_SYNC_DAYS = 90
_INTERVALS_DEFAULT_SYNC_DAYS = 84
_GARMIN_DEFAULT_SYNC_DAYS = 84
_WAHOO_DEFAULT_SYNC_DAYS = 84

_INTERVALS_NOT_CONFIGURED_MESSAGE = (
    "Intervals.icu ist nicht konfiguriert. Bitte INTERVALS_API_KEY in der "
    "Serverkonfiguration hinterlegen."
)
_GARMIN_NOT_CONFIGURED_MESSAGE = (
    "Garmin ist nicht konfiguriert. Bitte GARMIN_EMAIL oder einen vorhandenen "
    "Garmin-Tokenstore einrichten."
)
WAHOO_NOT_CONFIGURED_MESSAGE = (
    "Wahoo ist nicht verbunden. Bitte Wahoo in den Einstellungen verbinden."
)

_ALL_INTERVALS_JOB_TYPES = frozenset(
    {
        "refresh",
        "performance_refresh",
        "activity_details",
        "plan_push",
        "competition_push",
        "nutrition_sync",
        "historical_backfill",
    }
)


class Capability(StrEnum):
    ACTIVITIES = "activities"
    ACTIVITY_DETAILS = "activity_details"
    DAILY_HEALTH = "daily_health"
    BODY = "body"
    THRESHOLDS = "thresholds"
    GEAR = "gear"
    PLANNED_EVENTS = "planned_events"
    COMPETITIONS = "competitions"
    WORKOUT_EXPORT = "workout_export"
    METRIC_EXPORT = "metric_export"
    WEATHER_FORECAST = "weather_forecast"
    PUBLIC_CALENDAR = "public_calendar"


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _require_positive_int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_optional_positive_int(value: object, name: str) -> None:
    if value is not None:
        _require_positive_int(value, name)


def _require_optional_rank(value: object, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")


def _require_text_set(value: object, name: str) -> None:
    if not isinstance(value, frozenset):
        raise TypeError(f"{name} must be a frozenset of text")
    for item in value:
        _require_text(item, name)


def _require_route_path(value: object, name: str) -> None:
    _require_text(value, name)
    if not str(value).startswith("/"):
        raise ValueError(f"{name} must be an absolute path")


@dataclass(frozen=True, slots=True)
class FreshnessArea:
    """One freshness-tracked area of a provider and how it is presented."""

    area: str
    label: str
    stale_after_s: int
    read_only: bool

    def __post_init__(self) -> None:
        _require_text(self.area, "area")
        _require_text(self.label, "label")
        _require_positive_int(self.stale_after_s, "stale_after_s")
        if not isinstance(self.read_only, bool):
            raise TypeError("read_only must be a boolean")


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    """When a provider is scheduled and whether it keeps daily markers.

    ``None`` for a rank means the provider is never scheduled in that run.
    ``daily_marker`` enables the hourly due-check plus attempt and success
    markers used by the daily refresh.
    """

    daily_rank: int | None = None
    startup_rank: int | None = None
    daily_marker: bool = False

    def __post_init__(self) -> None:
        _require_optional_rank(self.daily_rank, "daily_rank")
        _require_optional_rank(self.startup_rank, "startup_rank")
        _require_bool(self.daily_marker, "daily_marker")


@dataclass(frozen=True, slots=True)
class ManualSyncRoute:
    """A user-facing POST route that enqueues a provider refresh.

    ``payload`` holds the fixed job fields the route adds, as ordered pairs.
    """

    path: str
    uses_sync_period: bool
    payload: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        _require_route_path(self.path, "path")
        _require_bool(self.uses_sync_period, "uses_sync_period")
        if not isinstance(self.payload, tuple) or not all(
            isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
            for item in self.payload
        ):
            raise ValueError("payload must be a tuple of (name, value) pairs")


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Provider-neutral description of one configured data provider.

    ``resync_keys`` holds the durable full-resync state keys in the order
    running, status, last completion, error. Providers without a full resync
    leave it empty.

    The orchestration fields default to the generic refresh-only behaviour.
    ``coach_rank`` of ``None`` means the provider is not a Coach refresh target.
    ``metric_exports`` names the metrics an explicit metric export may write and
    is non-empty exactly when the provider declares ``METRIC_EXPORT``.
    """

    provider_id: str
    label: str
    capabilities: frozenset[Capability]
    freshness_areas: tuple[FreshnessArea, ...]
    max_sync_days: int
    resync_keys: tuple[str, ...]
    job_types: frozenset[str] = frozenset({"refresh"})
    refresh_fields: frozenset[str] = frozenset({"reason"})
    default_sync_days: int | None = None
    schedule: SchedulePolicy = SchedulePolicy()
    coach_rank: int | None = None
    coach_waits_for_completion: bool = False
    not_configured_message: str | None = None
    manual_sync: ManualSyncRoute | None = None
    full_resync_path: str | None = None
    metric_exports: frozenset[MetricKind] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        _require_text(self.label, "label")
        if not isinstance(self.capabilities, frozenset) or not all(
            isinstance(capability, Capability) for capability in self.capabilities
        ):
            raise ValueError("capabilities must be a frozenset of Capability values")
        if not isinstance(self.freshness_areas, tuple) or not all(
            isinstance(area, FreshnessArea) for area in self.freshness_areas
        ):
            raise ValueError("freshness_areas must be a tuple of FreshnessArea values")
        _require_positive_int(self.max_sync_days, "max_sync_days")
        if not isinstance(self.resync_keys, tuple):
            raise TypeError("resync_keys must be a tuple of key names")
        for key in self.resync_keys:
            _require_text(key, "resync key")
        if len(set(self.resync_keys)) != len(self.resync_keys):
            raise ValueError("resync_keys must be unique")
        _require_text_set(self.job_types, "job_types")
        _require_text_set(self.refresh_fields, "refresh_fields")
        _require_optional_positive_int(self.default_sync_days, "default_sync_days")
        if (
            self.default_sync_days is not None
            and self.default_sync_days > self.max_sync_days
        ):
            raise ValueError("default_sync_days must not exceed max_sync_days")
        if not isinstance(self.schedule, SchedulePolicy):
            raise TypeError("schedule must be a SchedulePolicy")
        _require_optional_rank(self.coach_rank, "coach_rank")
        _require_bool(self.coach_waits_for_completion, "coach_waits_for_completion")
        if self.not_configured_message is not None:
            _require_text(self.not_configured_message, "not_configured_message")
        if self.manual_sync is not None and not isinstance(
            self.manual_sync, ManualSyncRoute
        ):
            raise ValueError("manual_sync must be a ManualSyncRoute")
        if self.full_resync_path is not None:
            _require_route_path(self.full_resync_path, "full_resync_path")
        if not isinstance(self.metric_exports, frozenset) or not all(
            isinstance(kind, MetricKind) for kind in self.metric_exports
        ):
            raise ValueError("metric_exports must be a frozenset of MetricKind values")
        if bool(self.metric_exports) != (Capability.METRIC_EXPORT in self.capabilities):
            raise ValueError("metric_exports must be declared with METRIC_EXPORT")


DEFAULT_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_id=INTERVALS_ID,
        label="Intervals.icu",
        capabilities=frozenset(
            {
                Capability.ACTIVITIES,
                Capability.ACTIVITY_DETAILS,
                Capability.DAILY_HEALTH,
                Capability.BODY,
                Capability.THRESHOLDS,
                Capability.GEAR,
                Capability.PLANNED_EVENTS,
                Capability.COMPETITIONS,
                Capability.WORKOUT_EXPORT,
                Capability.METRIC_EXPORT,
            }
        ),
        freshness_areas=(
            FreshnessArea(
                area="activities",
                label="Intervals.icu · Training",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=True,
            ),
            FreshnessArea(
                area="competitions",
                label="Intervals.icu · Wettkämpfe",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=False,
            ),
            FreshnessArea(
                area="performance",
                label="Intervals.icu · Leistung",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=_INTERVALS_MAX_SYNC_DAYS,
        resync_keys=(
            "intervals_full_resync_running",
            "intervals_full_resync_status",
            "intervals_full_resync_at",
            "intervals_full_resync_error",
        ),
        # Accepted job types; backend/sync/jobs.py checks them via supports_job.
        job_types=_ALL_INTERVALS_JOB_TYPES,
        # Refresh payload fields; backend/sync/jobs.py enforces them via the
        # registry's refresh_fields.
        refresh_fields=frozenset({"days", "reason", "end_date"}),
        # Default sync window reported by ProviderRegistry.sync_period_defaults to
        # http_api public and bootstrap state. The sync services still take their
        # window from the separate server.py SYNC_PERIOD_DEFAULTS literal, so the
        # two values must be kept equal by hand.
        default_sync_days=_INTERVALS_DEFAULT_SYNC_DAYS,
        # Ranks feed ProviderRegistry.daily_order and startup_order; the daily
        # marker feeds backend/sync/daily.py and backend/sync/queue.py.
        schedule=SchedulePolicy(daily_rank=3, startup_rank=1, daily_marker=True),
        # Coach refresh order; ProviderRegistry.coach_refresh_targets reads it.
        coach_rank=1,
        # Coach waits for this refresh before answering (coach/tool_preparation.py).
        coach_waits_for_completion=True,
        # Message for not-configured responses (http_api/sync_commands.py).
        not_configured_message=_INTERVALS_NOT_CONFIGURED_MESSAGE,
        # Manual route with a sync period; http_api/sync_commands.py builds the
        # POST table from it.
        manual_sync=ManualSyncRoute(
            path="/api/sync",
            uses_sync_period=True,
            payload=(("reason", "manual"),),
        ),
        # Full-resync route; ProviderRegistry.full_resync_routes lists it.
        full_resync_path="/api/intervals/full-resync",
        # Body metrics go to the wellness day, thresholds to the Ride or Run sport
        # settings; backend/sync/intervals_metric_export.py maps the fields.
        metric_exports=frozenset(
            {
                MetricKind.WEIGHT,
                MetricKind.BODY_FAT,
                MetricKind.RESTING_HR,
                MetricKind.FTP,
                MetricKind.THRESHOLD_HR,
                MetricKind.MAX_HR,
                MetricKind.THRESHOLD_PACE,
            }
        ),
    ),
    ProviderDescriptor(
        provider_id=GARMIN_ID,
        label="Garmin",
        capabilities=frozenset(
            {
                Capability.ACTIVITIES,
                Capability.ACTIVITY_DETAILS,
                Capability.DAILY_HEALTH,
                Capability.BODY,
                Capability.THRESHOLDS,
                Capability.GEAR,
            }
        ),
        freshness_areas=(
            FreshnessArea(
                area="data",
                label="Garmin",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=DEFAULT_MAX_SYNC_DAYS,
        resync_keys=(
            "garmin_full_resync_running",
            "garmin_full_resync_status",
            "garmin_full_resync_at",
            "garmin_full_resync_error",
        ),
        # historical_backfill is accepted here; backend/sync/jobs.py rejects it for
        # providers that do not declare it.
        job_types=frozenset({"refresh", "historical_backfill"}),
        # Refresh payload fields; backend/sync/jobs.py enforces them via the registry.
        refresh_fields=frozenset({"days", "reason", "end_date"}),
        default_sync_days=_GARMIN_DEFAULT_SYNC_DAYS,
        schedule=SchedulePolicy(daily_rank=2, startup_rank=2, daily_marker=True),
        coach_rank=2,
        # Coach waits for this refresh so a check-in never reads stale recovery data.
        coach_waits_for_completion=True,
        not_configured_message=_GARMIN_NOT_CONFIGURED_MESSAGE,
        manual_sync=ManualSyncRoute(
            path="/api/garmin/sync",
            uses_sync_period=True,
            payload=(("reason", "manual"),),
        ),
        full_resync_path="/api/garmin/full-resync",
    ),
    ProviderDescriptor(
        provider_id=WEATHER_ID,
        label="Open-Meteo",
        capabilities=frozenset({Capability.WEATHER_FORECAST}),
        freshness_areas=(
            FreshnessArea(
                area="forecast",
                label="Open-Meteo",
                stale_after_s=_THREE_HOURS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=DEFAULT_MAX_SYNC_DAYS,
        resync_keys=(),
        # Refresh payload fields; backend/sync/jobs.py enforces them via the registry.
        refresh_fields=frozenset({"force", "reason"}),
        schedule=SchedulePolicy(daily_rank=0, startup_rank=3, daily_marker=False),
        coach_rank=4,
        # Forced manual weather refresh (http_api/sync_commands.py).
        manual_sync=ManualSyncRoute(
            path="/api/weather/sync",
            uses_sync_period=False,
            payload=(("reason", "manuell"), ("force", True)),
        ),
    ),
    ProviderDescriptor(
        provider_id=CALENDAR_ID,
        label="Gemeinsamer Kalender",
        capabilities=frozenset({Capability.PUBLIC_CALENDAR}),
        freshness_areas=(
            FreshnessArea(
                area="events",
                label="Gemeinsamer Kalender",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=DEFAULT_MAX_SYNC_DAYS,
        resync_keys=(),
        schedule=SchedulePolicy(daily_rank=1, startup_rank=0, daily_marker=True),
        coach_rank=3,
        manual_sync=ManualSyncRoute(
            path="/api/external-calendar/sync",
            uses_sync_period=False,
            payload=(("reason", "manuell"),),
        ),
    ),
    ProviderDescriptor(
        provider_id=WAHOO_ID,
        label="Wahoo",
        # Workout ingest, the granted power zones and profile as lowest-priority
        # threshold and body sources, plus plan export of local library workouts
        # that only runs on the athlete's explicit library sync with Wahoo as the target.
        capabilities=frozenset(
            {
                Capability.ACTIVITIES,
                Capability.BODY,
                Capability.THRESHOLDS,
                Capability.WORKOUT_EXPORT,
            }
        ),
        freshness_areas=(
            FreshnessArea(
                area="activities",
                label="Wahoo",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=DEFAULT_MAX_SYNC_DAYS,
        resync_keys=(
            "wahoo_full_resync_running",
            "wahoo_full_resync_status",
            "wahoo_full_resync_at",
            "wahoo_full_resync_error",
        ),
        # plan_push is the explicit library export; backend/sync/jobs.py checks it.
        job_types=frozenset({"refresh", "plan_push"}),
        refresh_fields=frozenset({"days", "reason"}),
        default_sync_days=_WAHOO_DEFAULT_SYNC_DAYS,
        # Ranked after every earlier provider in the daily, startup and Coach order.
        schedule=SchedulePolicy(daily_rank=4, startup_rank=4, daily_marker=True),
        coach_rank=5,
        not_configured_message=WAHOO_NOT_CONFIGURED_MESSAGE,
        # Manual refresh uses the window of the handler's default, not the stored
        # period, so the route does not read a sync period.
        manual_sync=ManualSyncRoute(
            path="/api/wahoo/sync",
            uses_sync_period=False,
            payload=(("reason", "manual"),),
        ),
        full_resync_path="/api/wahoo/full-resync",
    ),
)
