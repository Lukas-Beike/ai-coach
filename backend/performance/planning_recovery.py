"""Date-indexed recovery values used by the planning context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import recovery as performance_recovery
from backend.performance import wellness as performance_wellness
from backend.performance.source_policy import select_daily
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import GARMIN_RESTING_HR_ALIASES
from backend.runtime.ports import ObservationReader

GARMIN_SOURCE = "Garmin Connect"
INTERVALS_WELLNESS_SOURCE = "Intervals.icu Wellness"
UTC_OFFSET_SUFFIX = "+00:00"
_ROW_DATE_KEYS = garmin_perf_fields.PLANNING_ROW_DATE_KEYS
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
_LOAD_FIELDS: tuple[tuple[str, MetricKind], ...] = (
    ("ctl", MetricKind.CTL),
    ("atl", MetricKind.ATL),
)


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


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


def _planning_sleep_hours(
    record: dict[str, Any], seconds_fields: tuple[str, ...]
) -> float | None:
    sleep_hours = _as_number(record.get("sleep_hours"))
    sleep_seconds = _first_present(record, seconds_fields)
    if sleep_hours is not None or sleep_seconds in (None, ""):
        return sleep_hours
    try:
        return round(float(sleep_seconds) / 3600, 1)
    except TypeError, ValueError:
        return None


def _add_intervals_planning_recovery(
    recovery_by_date: dict[str, dict[str, Any]], rows: Any
) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        record_date = _planning_context_date(_first_present(row, _ROW_DATE_KEYS))
        if not record_date:
            continue
        recovery = recovery_by_date.setdefault(record_date, {})
        _add_planning_recovery_value(
            recovery,
            "sleep_hours",
            _planning_sleep_hours(row, ("sleepSecs", "sleep_seconds")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "sleep_score",
            _first_present(row, ("sleepScore", "overallSleepScore")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "hrv",
            _first_present(row, ("hrv", "hrv_ms")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "readiness",
            performance_wellness.readiness_score_value(
                _first_present(
                    row,
                    (
                        "readiness",
                        "readinessScore",
                        "readiness_score",
                        "trainingReadiness",
                        "training_readiness",
                    ),
                )
            ),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "resting_hr",
            _first_present(row, ("restingHR", "resting_hr")),
            INTERVALS_WELLNESS_SOURCE,
        )
        for metric_name, keys in (
            ("ctl", ("ctl", "ctLoad")),
            ("atl", ("atl", "atlLoad")),
            ("tsb", ("tsb", "form")),
        ):
            _add_planning_recovery_value(
                recovery,
                metric_name,
                _first_present(row, keys),
                INTERVALS_WELLNESS_SOURCE,
            )


def _add_garmin_planning_recovery_record(
    recovery: dict[str, Any], section: str, record: dict[str, Any]
) -> None:
    if section == "sleep":
        _add_planning_recovery_value(
            recovery,
            "sleep_hours",
            _planning_sleep_hours(record, garmin_perf_fields.SLEEP_DURATION_ALIASES),
            GARMIN_SOURCE,
            overwrite=True,
        )
        _add_planning_recovery_value(
            recovery,
            "sleep_score",
            _first_present(record, ("sleepScore", "overallSleepScore")),
            GARMIN_SOURCE,
            overwrite=True,
        )
    elif section == "hrv":
        _add_planning_recovery_value(
            recovery,
            "hrv",
            _first_present(record, garmin_perf_fields.HRV_WITH_WEEKLY_ALIASES),
            GARMIN_SOURCE,
            overwrite=True,
        )
    elif section == "resting_hr":
        _add_planning_recovery_value(
            recovery,
            "resting_hr",
            _first_present(record, GARMIN_RESTING_HR_ALIASES),
            GARMIN_SOURCE,
            overwrite=True,
        )
    else:
        _add_planning_recovery_value(
            recovery,
            "readiness",
            performance_wellness.readiness_score_value(
                _first_present(
                    record,
                    garmin_perf_fields.PLANNING_READINESS_ALIASES,
                )
            ),
            GARMIN_SOURCE,
        )


def _add_garmin_planning_recovery(
    recovery_by_date: dict[str, dict[str, Any]], garmin: Any
) -> None:
    if not isinstance(garmin, dict):
        return
    for section in ("sleep", "hrv", "resting_hr", "readiness"):
        for record_date, record in performance_recovery.dated_garmin_recovery_records(
            garmin.get(section)
        ):
            _add_garmin_planning_recovery_record(
                recovery_by_date.setdefault(record_date, {}), section, record
            )


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


def planning_recovery_by_date(
    wellness_rows: Any,
    garmin: Any,
    morning_battery_history: Any,
    morning_body_battery: Any,
) -> dict[str, dict[str, Any]]:
    """Build a date-indexed recovery view from stored provider snapshots.

    This is the reference reader of the stored-snapshot shape. The planning context
    reads ``planning_recovery_view`` instead, and the source-policy tests compare
    the two on the same data.
    """
    recovery_by_date: dict[str, dict[str, Any]] = {}
    _add_intervals_planning_recovery(recovery_by_date, wellness_rows)
    _add_garmin_planning_recovery(recovery_by_date, garmin)
    _add_morning_battery_recovery(
        recovery_by_date, morning_battery_history, morning_body_battery
    )
    return recovery_by_date


def _canonical_value(kind: MetricKind, observation: Observation) -> float | int:
    """Return the planning value of an observation.

    Sleep duration is stored in seconds and shown in hours. Whole numbers are shown
    as integers, as the other planning values are.
    """
    value = observation.value.value
    if kind is MetricKind.SLEEP_DURATION:
        return round(float(value) / 3600, 1)
    return int(value) if float(value).is_integer() else value


def first_intervals_by_day(
    observations: Iterable[Observation],
) -> dict[date, Observation]:
    """Return the first Intervals.icu observation of each day."""
    first: dict[date, Observation] = {}
    for observation in observations:
        if observation.provenance.provider is ProviderId.INTERVALS:
            first.setdefault(observation.observed_on, observation)
    return first


def canonical_planning_recovery(
    reader: ObservationReader, db: Any, *, start: date, end: date
) -> dict[str, dict[str, Any]]:
    """Build the date-indexed recovery view from canonical observations.

    ``reader`` must already be the source chosen for the unit of work. Each value
    is the observation the daily source rule selects for its day: Garmin before
    Intervals.icu for sleep, HRV and resting HR, the reverse for readiness. CTL and
    ATL come from Intervals.icu only. Every value carries the source label of the
    provider that supplied it.
    """
    recovery_by_date: dict[str, dict[str, Any]] = {}
    for field, kind in _DAILY_FIELDS:
        selected = select_daily(
            reader.observations(db, kind, start=start, end=end), kind
        )
        _add_observations(recovery_by_date, field, kind, selected)
    for field, kind in _LOAD_FIELDS:
        loaded = first_intervals_by_day(
            reader.observations(db, kind, start=start, end=end)
        )
        _add_observations(recovery_by_date, field, kind, loaded)
    return recovery_by_date


def _add_observations(
    recovery_by_date: dict[str, dict[str, Any]],
    field: str,
    kind: MetricKind,
    observations: Mapping[date, Observation],
) -> None:
    for day, observation in observations.items():
        source = _SOURCE_BY_PROVIDER.get(observation.provenance.provider)
        if source is None:
            continue
        _add_planning_recovery_value(
            recovery_by_date.setdefault(day.isoformat(), {}),
            field,
            _canonical_value(kind, observation),
            source,
        )


def add_intervals_form(
    recovery_by_date: dict[str, dict[str, Any]],
    wellness_rows: Any,
    *,
    start: date,
    end: date,
) -> None:
    """Add the Intervals.icu form (TSB) of each day in the window.

    Form has no canonical observation, so it stays a read of the stored wellness
    rows. Nothing else is read from them, and the window comes from the caller.
    """
    if not isinstance(wellness_rows, list):
        return
    for row in wellness_rows:
        if not isinstance(row, dict):
            continue
        record_date = _planning_context_date(_first_present(row, _ROW_DATE_KEYS))
        form = _first_present(row, ("tsb", "form"))
        if form is None or not start.isoformat() <= record_date <= end.isoformat():
            continue
        _add_planning_recovery_value(
            recovery_by_date.setdefault(record_date, {}),
            "tsb",
            form,
            INTERVALS_WELLNESS_SOURCE,
        )


def planning_recovery_view(
    reader: ObservationReader,
    db: Any,
    *,
    start: date,
    end: date,
    wellness_rows: Any,
    morning_battery_history: Any,
    morning_body_battery: Any,
) -> dict[str, dict[str, Any]]:
    """Combine canonical recovery with the values that have no canonical form.

    Form (TSB) comes from the stored wellness rows and body battery from the
    morning history and the current morning reading.
    """
    recovery_by_date = canonical_planning_recovery(reader, db, start=start, end=end)
    add_intervals_form(recovery_by_date, wellness_rows, start=start, end=end)
    _add_morning_battery_recovery(
        recovery_by_date, morning_battery_history, morning_body_battery
    )
    return recovery_by_date
