"""Weather-cache keys and persistence-safe invalidation rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.weather import projection, recommendations

CACHE_KEY = "weather_cache"
FAILURE_KEY = "weather_failure"
HISTORY_KEY = "calendar_weather_history"


@dataclass
class WeatherCacheState:
    query: str
    cached: dict[str, Any]
    failure: dict[str, Any]
    previous_failure_count: int
    cache_matches: bool
    cache_age: float
    error: str | None = None
    refreshed: bool = False


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value.copy()
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _failure_count(failure: dict[str, Any]) -> int:
    try:
        return max(0, int(failure.get("count") or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc(value: Any) -> datetime:
    return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def cache_state(
    query: str,
    cached_value: Any,
    failure_value: Any,
    *,
    now: datetime,
    cache_seconds: int = 10800,
) -> WeatherCacheState:
    cached = _record(cached_value)
    failure = _record(failure_value)
    cache_matches = cached.get("query") == query and isinstance(
        cached.get("forecast"), dict
    )
    try:
        cache_age = (
            (_as_utc(now) - _parse_utc(cached.get("fetched_at") or "")).total_seconds()
            if cache_matches
            else float("inf")
        )
    except (TypeError, ValueError, OverflowError):
        cache_age = float("inf")
    error = (
        "Wetterdaten sind veraltet."
        if cache_matches and (cache_age >= cache_seconds or failure)
        else None
    )
    return WeatherCacheState(
        query,
        cached,
        failure,
        _failure_count(failure),
        cache_matches,
        cache_age,
        error,
    )


def retry_wait(failure: Any, *, now: datetime) -> float:
    try:
        return (
            _parse_utc(_record(failure).get("retry_at")) - _as_utc(now)
        ).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return 0


def failure_record(
    previous_failure_count: Any,
    *,
    now: datetime,
    base_seconds: int = 900,
    max_seconds: int = 21600,
) -> dict[str, Any]:
    count = _failure_count({"count": previous_failure_count}) + 1
    delay = min(base_seconds * (2 ** min(count - 1, 5)), max_seconds)
    failed_at = _as_utc(now)
    return {
        "count": count,
        "failed_at": failed_at.isoformat(),
        "retry_at": (failed_at + timedelta(seconds=delay)).isoformat(),
    }


def unavailable_state(refresh: bool, error: str | None) -> dict[str, Any]:
    if not refresh:
        return {
            "configured": True,
            "state": "loading",
            "provider": "Open-Meteo",
            "days": [],
            "recommendations": [],
            "loading": True,
            "message": "Wetterdaten werden nachgeladen.",
        }
    return {
        "configured": True,
        "state": "error",
        "provider": "Open-Meteo",
        "days": [],
        "recommendations": [],
        "error": error or "Wetterdaten sind nicht verfügbar.",
    }


def ready_state(
    state: WeatherCacheState,
    planned: list[dict[str, Any]] | None,
    *,
    today: date,
) -> dict[str, Any]:
    forecast = state.cached.get("forecast")
    if not isinstance(forecast, dict):
        forecast = {}
    result = {
        "configured": True,
        "state": "stale" if state.error else "ready",
        "provider": "Open-Meteo",
        "attribution": "Wetterdaten: Open-Meteo.com (CC BY 4.0)",
        "model": state.cached.get("model"),
        "location": state.cached.get("location"),
        "fetched_at": state.cached.get("fetched_at"),
        "days": projection.daily_summary(forecast),
        "recommendations": recommendations.weather_recommendations(
            planned, forecast, today
        ),
    }
    if state.error:
        result["error"] = state.error
        result["stale"] = True
    if state.refreshed:
        result["_refreshed"] = True
    return result


def invalidate_for_location_change(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    repository: Any,
    db: Any,
) -> bool:
    """Clear cached weather state atomically when its location changes."""
    if previous.get("weather_location", "") == current.get("weather_location", ""):
        return False
    repository.set(db, CACHE_KEY, "")
    repository.set(db, FAILURE_KEY, "")
    return True
