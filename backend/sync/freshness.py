"""Read-only projection of the freshness of configured data providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import Config
from backend.sync.refresh import cleanup_refresh_history

WEATHER_CACHE_KEY = "weather_cache"
WEATHER_FAILURE_KEY = "weather_failure"
UTC_OFFSET_SUFFIX = "+00:00"
PROVIDER_REFRESH_RETENTION_DAYS = 30
PROVIDER_REFRESH_MAX_ROWS = 200
PROVIDER_REFRESH_STALE_SECONDS = {
    ("intervals", "activities"): 48 * 60 * 60,
    ("intervals", "competitions"): 48 * 60 * 60,
    ("intervals", "performance"): 48 * 60 * 60,
    ("garmin", "data"): 48 * 60 * 60,
    ("weather", "forecast"): 3 * 60 * 60,
    ("calendar", "events"): 48 * 60 * 60,
}
PROVIDER_REFRESH_LABELS = {
    ("intervals", "activities"): "Intervals.icu · Training",
    ("intervals", "competitions"): "Intervals.icu · Wettkämpfe",
    ("intervals", "performance"): "Intervals.icu · Leistung",
    ("garmin", "data"): "Garmin",
    ("weather", "forecast"): "Open-Meteo",
    ("calendar", "events"): "Gemeinsamer Kalender",
}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", UTC_OFFSET_SUFFIX))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _scheduled_provider_retry_at(db: Any, provider: str, *, now: datetime) -> str | None:
    """Return only a future queued retry, never an advisory history timestamp."""
    rows = db.execute(
        "SELECT available_at FROM sync_jobs "
        "WHERE provider=? AND type='refresh' "
        "AND status='queued' AND available_at IS NOT NULL ORDER BY available_at",
        (provider,),
    ).fetchall()
    for row in rows:
        available_at = _parse_utc(row["available_at"])
        if available_at is not None and available_at > now:
            return available_at.isoformat()
    return None


def _provider_freshness_inputs(
    *,
    config: Config,
    get_value: Callable[[str], str | None],
    profile: Mapping[str, Any],
    garmin_has_core_error: bool,
    garmin_tokenstore_exists: bool,
) -> tuple[dict[tuple[str, str], Any], dict[tuple[str, str], Any], dict[tuple[str, str], bool]]:
    fallbacks = {
        ("intervals", "activities"): get_value("last_sync_at"),
        ("intervals", "competitions"): get_value("last_competition_sync_at"),
        ("intervals", "performance"): get_value("last_performance_refresh_at"),
        ("garmin", "data"): get_value("last_garmin_sync_at"),
        ("weather", "forecast"): None,
        ("calendar", "events"): get_value("last_external_calendar_sync_at"),
    }
    fallback_errors = {
        ("intervals", "activities"): get_value("last_sync_error"),
        ("intervals", "competitions"): get_value("last_competition_sync_error"),
        ("intervals", "performance"): get_value("last_performance_error"),
        ("garmin", "data"): garmin_has_core_error,
        ("weather", "forecast"): get_value(WEATHER_FAILURE_KEY),
        ("calendar", "events"): get_value("last_external_calendar_sync_error"),
    }
    try:
        cached_weather = json.loads(get_value(WEATHER_CACHE_KEY) or "{}")
        if isinstance(cached_weather, dict):
            fallbacks[("weather", "forecast")] = cached_weather.get("fetched_at")
    except (TypeError, ValueError):
        pass
    configured = {
        ("intervals", "activities"): bool(config.intervals_api_key),
        ("intervals", "competitions"): bool(config.intervals_api_key),
        ("intervals", "performance"): bool(config.intervals_api_key),
        ("garmin", "data"): bool(config.garmin_fixture_path or config.garmin_email or garmin_tokenstore_exists),
        ("weather", "forecast"): bool(profile.get("weather_location")),
        ("calendar", "events"): bool(config.calendar_ical_url),
    }
    return fallbacks, fallback_errors, configured


def _provider_freshness_last_good_state(key: tuple[str, str], last_good: Any, *, now: datetime) -> str:
    parsed = _parse_utc(last_good)
    if parsed is None:
        return "stale" if last_good else "error"
    age = (now - parsed).total_seconds()
    return "stale" if age > PROVIDER_REFRESH_STALE_SECONDS[key] else "fresh"


def _provider_fallback_error_code(fallback_error: bool) -> str | None:
    return "provider_error" if fallback_error else None


def _provider_freshness_error_code(row: Mapping[str, Any] | None, fallback_error: bool) -> str | None:
    if row:
        error_code = str(row.get("error_code") or "")
        if error_code:
            return error_code
    return _provider_fallback_error_code(fallback_error)


def _provider_freshness_status(
    key: tuple[str, str], configured: bool, row: Mapping[str, Any] | None,
    last_good: Any, fallback_error: bool, *, now: datetime,
) -> tuple[str, str | None]:
    if not configured:
        return "not_configured", _provider_freshness_error_code(row, fallback_error)
    if row:
        status = row["status"]
        if status == "running":
            return "syncing", _provider_fallback_error_code(fallback_error)
        if status == "error":
            state = "stale" if last_good else "error"
            return state, row.get("error_code")
        if status == "partial":
            return "partial", _provider_fallback_error_code(fallback_error)
    if last_good:
        return _provider_freshness_last_good_state(key, last_good, now=now), _provider_fallback_error_code(fallback_error)
    if fallback_error:
        return "error", "provider_error"
    return "never_loaded", None


def provider_freshness_state(
    db: Any,
    *,
    config: Config,
    get_value: Callable[[str], str | None],
    profile: Mapping[str, Any],
    garmin_has_core_error: bool,
    garmin_tokenstore_exists: bool,
    now: datetime,
    retention_days: int = PROVIDER_REFRESH_RETENTION_DAYS,
    max_rows: int = PROVIDER_REFRESH_MAX_ROWS,
) -> list[dict[str, Any]]:
    """Build the provider freshness projection on a caller-owned connection.

    The cleanup intentionally remains uncommitted: the caller owns transaction
    boundaries and may roll back the diagnostic cleanup together with its work.
    """
    current_time = now.astimezone(timezone.utc) if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    fallbacks, fallback_errors, configured = _provider_freshness_inputs(
        config=config,
        get_value=get_value,
        profile=profile,
        garmin_has_core_error=garmin_has_core_error,
        garmin_tokenstore_exists=garmin_tokenstore_exists,
    )
    cutoff = (current_time - timedelta(days=retention_days)).isoformat()
    cleanup_refresh_history(db, cutoff=cutoff, max_rows=max_rows)
    result: list[dict[str, Any]] = []
    for key, label in PROVIDER_REFRESH_LABELS.items():
        provider, area = key
        row = db.execute(
            "SELECT * FROM provider_refresh_history WHERE provider=? AND area=? ORDER BY started_at DESC LIMIT 1",
            (provider, area),
        ).fetchone()
        last_success = db.execute(
            "SELECT finished_at FROM provider_refresh_history WHERE provider=? AND area=? AND status IN ('success','partial') "
            "ORDER BY finished_at DESC LIMIT 1",
            (provider, area),
        ).fetchone()
        row = dict(row) if row else None
        fallback = fallbacks[key]
        fallback_error = bool(fallback_errors[key])
        last_attempt = row.get("started_at") if row else fallback
        last_good = (last_success["finished_at"] if last_success else None) or fallback
        scheduled_retry = _scheduled_provider_retry_at(db, provider, now=current_time)
        state, error_code = _provider_freshness_status(
            key, configured[key], row, last_good, fallback_error, now=current_time,
        )
        result.append({
            "provider": provider,
            "area": area,
            "label": label,
            "configured": configured[key],
            "read_only": key != ("intervals", "competitions"),
            "state": state,
            "phase": row.get("phase") if row else None,
            "last_attempt_at": last_attempt,
            "last_success_at": last_good,
            "error_code": error_code,
            "next_retry_at": scheduled_retry,
            "stale": state == "stale",
            "has_last_good": bool(last_good),
        })
    return result
