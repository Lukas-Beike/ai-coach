"""Declarative descriptors for external data providers.

The descriptors hold provider data that synchronization used to keep in literal
tables: freshness areas and labels, sync-window limits, and the durable keys of
full-resync state. They name providers by design, so they live in the provider
package, which the provider coupling ratchet exempts. The sync registry
(backend/sync/provider_registry.py) reads them and names no provider.

Migration is incomplete: the freshness projection still keeps its per-area
fallback sources and configured predicates in backend/sync/freshness.py, and
those must move into descriptors in a later change.

Capabilities describe what each provider can supply. They are declarative and
have no production consumer yet; ``ProviderRegistry.ids_with`` is their only
reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.canonical.vocabulary import ProviderId

_TWO_DAYS_SECONDS = 48 * 60 * 60
_THREE_HOURS_SECONDS = 3 * 60 * 60
_INTERVALS_MAX_SYNC_DAYS = 365
DEFAULT_MAX_SYNC_DAYS = 90


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
    WEATHER_FORECAST = "weather_forecast"
    PUBLIC_CALENDAR = "public_calendar"


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _require_positive_int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


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
class ProviderDescriptor:
    """Provider-neutral description of one configured data provider.

    ``resync_keys`` holds the durable full-resync state keys in the order
    running, status, last completion, error. Providers without a full resync
    leave it empty.
    """

    provider_id: str
    label: str
    capabilities: frozenset[Capability]
    freshness_areas: tuple[FreshnessArea, ...]
    max_sync_days: int
    resync_keys: tuple[str, ...]

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


DEFAULT_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_id=ProviderId.INTERVALS.value,
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
    ),
    ProviderDescriptor(
        provider_id=ProviderId.GARMIN.value,
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
    ),
    ProviderDescriptor(
        provider_id="weather",
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
    ),
    ProviderDescriptor(
        provider_id="calendar",
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
    ),
)
