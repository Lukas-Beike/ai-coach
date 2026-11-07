"""Date-indexed recovery values used by the planning context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.fitness_fatigue import SOURCE_LABEL
from backend.performance.source_policy import (
    FAMILY_LOOKBACK_DAYS,
    METHOD_FAMILY_KINDS,
    NO_PREFERENCES,
    SourcePreferences,
    family_providers,
    intervals_relays_garmin,
    select_daily,
)
from backend.runtime.ports import ObservationReader

GARMIN_SOURCE = "Garmin Connect"
INTERVALS_WELLNESS_SOURCE = "Intervals.icu Wellness"
# An Intervals.icu value that relays Garmin's (``intervals_relays_garmin``).
INTERVALS_GARMIN_RELAY_SOURCE = "Intervals.icu Wellness (Garmin)"
UTC_OFFSET_SUFFIX = "+00:00"
_SOURCE_BY_PROVIDER: dict[ProviderId | None, str] = {
    ProviderId.GARMIN: GARMIN_SOURCE,
    ProviderId.INTERVALS: INTERVALS_WELLNESS_SOURCE,
}
_DAILY_FIELDS: tuple[tuple[str, MetricKind], ...] = (
    ("sleep_hours", MetricKind.SLEEP_DURATION),
    ("sleep_score", MetricKind.SLEEP_SCORE),
    ("hrv", MetricKind.HRV_RMSSD),
    ("readiness", MetricKind.READINESS),
    ("resting_hr", MetricKind.RESTING_HR),
)
# Local fitness (M7) result keys by planning field; never Intervals.icu CTL/ATL.
_LOAD_FIELDS: tuple[tuple[str, str], ...] = (
    ("ctl", "fitness"),
    ("atl", "fatigue"),
    ("tsb", "form"),
)
LOCAL_LOAD_SOURCE: Final = SOURCE_LABEL


def _planning_context_date(value: Any) -> str:
    raw = iso_date_prefix(str(value or "").replace("Z", UTC_OFFSET_SUFFIX))
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


def _add_planning_recovery_value(
    recovery: dict[str, Any],
    metric_name: str,
    value: Any,
    source: str,
    *,
    overwrite: bool = False,
) -> None:
    if value in (None, "") or (metric_name in recovery and not overwrite):
        return
    recovery[metric_name] = value
    recovery.setdefault("sources", {})[metric_name] = source


def _add_morning_battery_recovery(
    recovery_by_date: dict[str, dict[str, Any]],
    morning_battery_history: Any,
    morning_body_battery: Any,
) -> None:
    if isinstance(morning_battery_history, dict):
        for day, value in morning_battery_history.items():
            record_date = _planning_context_date(day)
            if record_date and _as_number(value) is not None:
                _add_planning_recovery_value(
                    recovery_by_date.setdefault(record_date, {}),
                    "body_battery",
                    value,
                    GARMIN_SOURCE,
                )
    if (
        isinstance(morning_body_battery, dict)
        and morning_body_battery.get("status") == "ready"
    ):
        record_date = _planning_context_date(morning_body_battery.get("sleep_date"))
        morning = morning_body_battery.get("morning")
        if record_date and isinstance(morning, dict):
            _add_planning_recovery_value(
                recovery_by_date.setdefault(record_date, {}),
                "body_battery",
                morning.get("value"),
                GARMIN_SOURCE,
                overwrite=True,
            )


def _canonical_value(kind: MetricKind, observation: Observation) -> float | int:
    """Return the planning value of an observation.

    Sleep duration is stored in seconds and shown in hours. Whole numbers are shown
    as integers, as the other planning values are.
    """
    value = observation.value.value
    if kind is MetricKind.SLEEP_DURATION:
        return round(float(value) / 3600, 1)
    return int(value) if float(value).is_integer() else value


def canonical_planning_recovery(
    reader: ObservationReader,
    db: Any,
    *,
    start: date,
    end: date,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> dict[str, dict[str, Any]]:
    """Build the date-indexed recovery view from canonical observations.

    ``reader`` must already be the source chosen for the unit of work. Each value
    is the observation the daily source rule selects for its day: Garmin's method
    family for sleep, HRV and resting HR (Intervals.icu only as its relay, or
    without any Garmin value), Intervals.icu before Garmin for readiness. Every
    value carries the source label of the provider that supplied it; a relay value
    is labelled as Garmin's. CTL, ATL and form are added by
    ``planning_recovery_view`` from the local curve.
    The method family is decided over ``FAMILY_LOOKBACK_DAYS`` ending on ``end``
    (or from ``start``, if earlier), the window the current recovery values use.
    """
    recovery_by_date: dict[str, dict[str, Any]] = {}
    family_start = min(start, end - timedelta(days=FAMILY_LOOKBACK_DAYS - 1))
    for field, kind in _DAILY_FIELDS:
        read_start = family_start if kind in METHOD_FAMILY_KINDS else start
        observations = tuple(reader.observations(db, kind, start=read_start, end=end))
        selected = {
            day: observation
            for day, observation in select_daily(
                observations, kind, preferences
            ).items()
            if day >= start
        }
        _add_observations(
            recovery_by_date,
            field,
            kind,
            selected,
            relay=ProviderId.GARMIN in family_providers(observations, kind, preferences)
            and intervals_relays_garmin(observations, kind),
        )
    return recovery_by_date


def _add_local_load(
    recovery_by_date: dict[str, dict[str, Any]],
    local_fitness_days: Sequence[Mapping[str, Any]],
) -> None:
    """Add the valued local fitness, fatigue and form (M7) of each day."""
    for day in local_fitness_days:
        for field, key in _LOAD_FIELDS:
            if day[key] is not None:
                _add_planning_recovery_value(
                    recovery_by_date.setdefault(day["date"], {}),
                    field,
                    day[key],
                    LOCAL_LOAD_SOURCE,
                )


def _add_observations(
    recovery_by_date: dict[str, dict[str, Any]],
    field: str,
    kind: MetricKind,
    observations: Mapping[date, Observation],
    *,
    relay: bool = False,
) -> None:
    for day, observation in observations.items():
        provider = observation.provenance.provider
        source = (
            INTERVALS_GARMIN_RELAY_SOURCE
            if relay and provider is ProviderId.INTERVALS
            else _SOURCE_BY_PROVIDER.get(provider)
        )
        if source is None:
            continue
        _add_planning_recovery_value(
            recovery_by_date.setdefault(day.isoformat(), {}),
            field,
            _canonical_value(kind, observation),
            source,
        )


def planning_recovery_view(
    reader: ObservationReader,
    db: Any,
    *,
    start: date,
    end: date,
    morning_battery_history: Any,
    morning_body_battery: Any,
    preferences: SourcePreferences = NO_PREFERENCES,
    local_fitness_days: Sequence[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Combine canonical recovery with the body battery and the local fitness.

    Body battery comes from the morning history and the current morning reading;
    CTL, ATL and form from the days of the local curve (card M7,
    ``read_local_fitness``); open and warm-up days have none.
    """
    recovery_by_date = canonical_planning_recovery(
        reader, db, start=start, end=end, preferences=preferences
    )
    _add_local_load(recovery_by_date, local_fitness_days)
    _add_morning_battery_recovery(
        recovery_by_date, morning_battery_history, morning_body_battery
    )
    return recovery_by_date
