"""Concrete freshness sources and running probes for the built-in providers.

The sources reproduce the fallbacks the freshness projection used before it was
registry-driven: stored last-sync settings, the cached weather timestamp and
provider signals that are not key-value settings. ``backend.sync.freshness``
consumes them by provider id and freshness area. Provider ids are the descriptor
constants, so this module names no provider as a string literal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Protocol

from backend.providers.descriptors import (
    CALENDAR_ID,
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
    WEATHER_ID,
)
from backend.sync.provider_runtime import FreshnessInputs, FreshnessSource
from backend.sync.wahoo_connection import WAHOO_TOKENS_KEY, connection_status
from backend.weather import cache as weather_cache

WEATHER_CACHE_KEY = weather_cache.CACHE_KEY
WEATHER_FAILURE_KEY = weather_cache.FAILURE_KEY
GARMIN_CORE_ERROR_SIGNAL = "garmin_has_core_error"
GARMIN_TOKENSTORE_SIGNAL = "garmin_tokenstore_exists"
INTERVALS_RUNNING_FLAG = "sync_running"


class _Lock(Protocol):
    def locked(self) -> bool: ...


def _stored_source(
    at_key: str,
    error_key: str,
    configured: Callable[[FreshnessInputs], bool],
) -> FreshnessSource:
    """Fall back to stored last-sync timestamp and error key-value settings."""
    return FreshnessSource(
        fallback_at=lambda inputs: inputs.get_value(at_key),
        fallback_error=lambda inputs: inputs.get_value(error_key),
        configured=configured,
    )


def _intervals_configured(inputs: FreshnessInputs) -> bool:
    return bool(inputs.config.intervals_api_key)


def _garmin_configured(inputs: FreshnessInputs) -> bool:
    config = inputs.config
    return bool(
        config.garmin_fixture_path
        or config.garmin_email
        or inputs.signals.get(GARMIN_TOKENSTORE_SIGNAL, False)
    )


def _wahoo_configured(inputs: FreshnessInputs) -> bool:
    """Wahoo counts as configured once the athlete connected it (tokens stored)."""
    status = connection_status(inputs.config, inputs.get_value(WAHOO_TOKENS_KEY))
    return bool(status["configured"] and status["connected"])


def _calendar_configured(inputs: FreshnessInputs) -> bool:
    return bool(inputs.config.calendar_ical_url)


def _weather_configured(inputs: FreshnessInputs) -> bool:
    return bool(inputs.profile.get("weather_location"))


def _weather_cached_at(inputs: FreshnessInputs) -> Any:
    """Return the cached forecast timestamp; unreadable caches yield None."""
    try:
        cached = json.loads(inputs.get_value(WEATHER_CACHE_KEY) or "{}")
    except TypeError, ValueError:
        return None
    if isinstance(cached, dict):
        return cached.get("fetched_at")
    return None


_INTERVALS_SOURCES: Mapping[str, FreshnessSource] = MappingProxyType(
    {
        "activities": _stored_source(
            "last_sync_at", "last_sync_error", _intervals_configured
        ),
        "competitions": _stored_source(
            "last_competition_sync_at",
            "last_competition_sync_error",
            _intervals_configured,
        ),
        "performance": _stored_source(
            "last_performance_refresh_at",
            "last_performance_error",
            _intervals_configured,
        ),
    }
)
_GARMIN_SOURCES: Mapping[str, FreshnessSource] = MappingProxyType(
    {
        "data": FreshnessSource(
            fallback_at=lambda inputs: inputs.get_value("last_garmin_sync_at"),
            fallback_error=lambda inputs: inputs.signals.get(
                GARMIN_CORE_ERROR_SIGNAL, False
            ),
            configured=_garmin_configured,
        ),
    }
)
_WAHOO_SOURCES: Mapping[str, FreshnessSource] = MappingProxyType(
    {
        "activities": _stored_source(
            "last_wahoo_sync_at", "last_wahoo_sync_error", _wahoo_configured
        ),
    }
)
_WEATHER_SOURCES: Mapping[str, FreshnessSource] = MappingProxyType(
    {
        "forecast": FreshnessSource(
            fallback_at=_weather_cached_at,
            fallback_error=lambda inputs: inputs.get_value(WEATHER_FAILURE_KEY),
            configured=_weather_configured,
        ),
    }
)
_CALENDAR_SOURCES: Mapping[str, FreshnessSource] = MappingProxyType(
    {
        "events": _stored_source(
            "last_external_calendar_sync_at",
            "last_external_calendar_sync_error",
            _calendar_configured,
        ),
    }
)

DEFAULT_FRESHNESS_SOURCES: Mapping[str, Mapping[str, FreshnessSource]] = (
    MappingProxyType(
        {
            INTERVALS_ID: _INTERVALS_SOURCES,
            GARMIN_ID: _GARMIN_SOURCES,
            WAHOO_ID: _WAHOO_SOURCES,
            WEATHER_ID: _WEATHER_SOURCES,
            CALENDAR_ID: _CALENDAR_SOURCES,
        }
    )
)


def intervals_sync_running(lock: _Lock, get_value: Callable[[str], Any]) -> bool:
    """Return whether an Intervals.icu sync is running: lock held or flag set.

    ``backend.sync.intervals`` delegates its runtime check here, so the lock and
    stored-flag rule has one implementation. The flag lives in key-value state
    and is compared exactly, so only the stored value ``"1"`` counts as running.
    """
    return bool(lock.locked()) or get_value(INTERVALS_RUNNING_FLAG) == "1"


def intervals_running_probe(
    lock: _Lock, get_value: Callable[[str], Any]
) -> Callable[[], bool]:
    """Return the Intervals.icu running check: its sync lock or the stored flag."""

    def running() -> bool:
        return intervals_sync_running(lock, get_value)

    return running


def default_running_probes(
    *,
    intervals_sync_lock: _Lock,
    get_value: Callable[[str], Any],
) -> Mapping[str, Callable[[], bool]]:
    """Return the running probes of today's built-in providers."""
    return MappingProxyType(
        {INTERVALS_ID: intervals_running_probe(intervals_sync_lock, get_value)}
    )
