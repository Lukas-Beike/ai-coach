"""The fixed table of the five providers synchronization knows.

One entry per provider holds its freshness areas and labels, sync-window
limits, the durable keys of full-resync state and the orchestration policy (job
types, scheduling order, Coach refresh targets, manual and full-resync HTTP
routes). A further provider is a new entry. This is the one sync module that
names providers; ``ProviderRegistry`` (backend/sync/provider_registry.py) reads
the table and names none.

The Garmin, Wahoo and Intervals.icu identifiers are canonical provider ids
(backend/canonical/vocabulary.py); weather and calendar are sync-only ids
defined here.

Capabilities describe what each provider can supply. ``ProviderRegistry.ids_with``
reads them, and the explicit library and metric exports check that their target
declares the export capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID, MetricKind

WEATHER_ID = "weather"
CALENDAR_ID = "calendar"

_TWO_DAYS_SECONDS = 48 * 60 * 60
_THREE_HOURS_SECONDS = 3 * 60 * 60
_INTERVALS_MAX_SYNC_DAYS = 365
DEFAULT_MAX_SYNC_DAYS = 90
_GARMIN_DEFAULT_SYNC_DAYS = 84
_WAHOO_DEFAULT_SYNC_DAYS = 84

_INTERVALS_NOT_CONFIGURED_MESSAGE = (
    "Intervals.icu ist nicht eingerichtet. Zugangsdaten unter Mehr → Anbindungen "
    "hinterlegen."
)
GARMIN_NOT_CONFIGURED_MESSAGE = (
    "Garmin ist nicht konfiguriert. Unter Mehr → Anbindungen bei Garmin anmelden "
    "oder einen Schlüssel der Garmin Personal API hinterlegen."
)
WAHOO_NOT_CONFIGURED_MESSAGE = (
    "Wahoo ist nicht verbunden. Bitte Wahoo in den Einstellungen verbinden."
)

_INTERVALS_OUTPUT_JOB_TYPES = frozenset(
    {
        "plan_push",
        "competition_push",
        "nutrition_sync",
    }
)


class Capability(StrEnum):
    ACTIVITIES = "activities"
    ACTIVITY_DETAILS = "activity_details"
    DAILY_HEALTH = "daily_health"
    BODY = "body"
    THRESHOLDS = "thresholds"
    GEAR = "gear"
    COMPETITIONS = "competitions"
    WORKOUT_EXPORT = "workout_export"
    METRIC_EXPORT = "metric_export"
    WEATHER_FORECAST = "weather_forecast"
    PUBLIC_CALENDAR = "public_calendar"


@dataclass(frozen=True, slots=True)
class FreshnessArea:
    """One freshness-tracked area of a provider and how it is presented."""

    area: str
    label: str
    stale_after_s: int
    read_only: bool


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


@dataclass(frozen=True, slots=True)
class ManualSyncRoute:
    """A user-facing POST route that enqueues a provider refresh.

    ``payload`` holds the fixed job fields the route adds, as ordered pairs.
    """

    path: str
    uses_sync_period: bool
    payload: tuple[tuple[str, object], ...] = ()


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


DEFAULT_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_id=INTERVALS_ID,
        label="Intervals.icu",
        # Output only: the app writes workouts, competitions, nutrition and
        # metrics to Intervals.icu and never reads training data from it.
        capabilities=frozenset(
            {
                Capability.COMPETITIONS,
                Capability.WORKOUT_EXPORT,
                Capability.METRIC_EXPORT,
            }
        ),
        freshness_areas=(
            FreshnessArea(
                area="competitions",
                label="Intervals.icu · Wettkämpfe",
                stale_after_s=_TWO_DAYS_SECONDS,
                read_only=False,
            ),
        ),
        max_sync_days=_INTERVALS_MAX_SYNC_DAYS,
        resync_keys=(),
        # Accepted job types; backend/sync/jobs.py checks them via supports_job.
        job_types=_INTERVALS_OUTPUT_JOB_TYPES,
        not_configured_message=_INTERVALS_NOT_CONFIGURED_MESSAGE,
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
        # providers that do not declare it. activity_details is the on-demand,
        # read-only Garmin detail fetch for one activity (see
        # backend/sync/garmin_activity_details.py); it is never scheduled.
        # plan_push is the explicit strength-workout push to the watch
        # (backend/sync/garmin_strength_push.py); it is never scheduled either.
        # wellness_backfill is the one-off, insert-only wellness history walk
        # (backend/sync/garmin_wellness_history.py), queued once at startup;
        # stream_backfill re-fetches the FIT streams of past activities
        # (backend/sync/stream_backfill.py).
        job_types=frozenset(
            {
                "refresh",
                "historical_backfill",
                "wellness_backfill",
                "stream_backfill",
                "activity_details",
                "plan_push",
            }
        ),
        # Refresh payload fields; backend/sync/jobs.py enforces them via the registry.
        refresh_fields=frozenset({"days", "reason", "end_date"}),
        default_sync_days=_GARMIN_DEFAULT_SYNC_DAYS,
        schedule=SchedulePolicy(daily_rank=2, startup_rank=2, daily_marker=True),
        coach_rank=2,
        # Coach waits for this refresh so a check-in never reads stale recovery data.
        coach_waits_for_completion=True,
        not_configured_message=GARMIN_NOT_CONFIGURED_MESSAGE,
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
        # stream_backfill re-fetches the FIT streams of past workouts
        # (backend/sync/stream_backfill.py).
        job_types=frozenset({"refresh", "plan_push", "stream_backfill"}),
        refresh_fields=frozenset({"days", "reason"}),
        default_sync_days=_WAHOO_DEFAULT_SYNC_DAYS,
        # Ranked after every earlier provider in the daily, startup and Coach order.
        schedule=SchedulePolicy(daily_rank=4, startup_rank=4, daily_marker=True),
        coach_rank=5,
        # Coach waits for the Wahoo refresh so a current-data answer reads fresh activities.
        coach_waits_for_completion=True,
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
