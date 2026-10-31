"""Daily-health normalization and aggregate projections.

Steps, floors and the total, active and resting energy come only from the
canonical observations (``read_daily_health_by_date``). Freshness and the read
windows are sync status and stay on the Garmin snapshot.
"""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import freshness as performance_freshness
from backend.providers.garmin_fields import (
    GARMIN_ACTIVE_KCAL_ALIASES,
    GARMIN_FLOORS_ALIASES,
    GARMIN_RESTING_KCAL_ALIASES,
    GARMIN_STEPS_ALIASES,
    GARMIN_TOTAL_KCAL_ALIASES,
)
from backend.providers.source_labels import SourceView, provider_label
from backend.runtime.ports import ObservationReader

GARMIN_PERFORMANCE_SOURCE = provider_label(ProviderId.GARMIN, SourceView.DAILY_HEALTH)

GARMIN_DAILY_HEALTH_FIELDS = {
    "steps": GARMIN_STEPS_ALIASES,
    "floors": GARMIN_FLOORS_ALIASES,
    "calories": GARMIN_TOTAL_KCAL_ALIASES,
}

GARMIN_DAILY_EXPENDITURE_FIELDS = {
    "active_kcal": GARMIN_ACTIVE_KCAL_ALIASES,
    "resting_kcal": GARMIN_RESTING_KCAL_ALIASES,
    "total_kcal": GARMIN_DAILY_HEALTH_FIELDS["calories"],
}

# Daily totals by canonical kind and the field of the date-indexed view.
DAILY_HEALTH_KINDS: Mapping[MetricKind, str] = {
    MetricKind.STEPS: "steps",
    MetricKind.FLOORS: "floors",
    MetricKind.DAILY_ENERGY_TOTAL: "calories",
    MetricKind.DAILY_ENERGY_ACTIVE: "active_kcal",
    MetricKind.DAILY_ENERGY_RESTING: "resting_kcal",
}


def _metric(
    value: Any, unit: str, source: str | None, note: str = ""
) -> dict[str, Any]:
    number = _as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "note": note if number is not None else "",
    }


def read_daily_health_by_date(
    reader: ObservationReader,
    db: Any,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the date-indexed daily totals from the canonical observations.

    ``reader`` must already be the source chosen for the unit of work. Each day
    maps ``steps``, ``floors``, ``calories``, ``active_kcal`` and ``resting_kcal``
    to its value. Per day and kind the latest observation wins; ``source`` names
    the providers of the day's values.
    """
    latest: dict[str, dict[str, Observation]] = {}
    for kind, name in DAILY_HEALTH_KINDS.items():
        for item in reader.observations(db, kind, start=start, end=end):
            day = latest.setdefault(item.observed_on.isoformat(), {})
            if name not in day or _order(item) >= _order(day[name]):
                day[name] = item
    health_by_date: dict[str, dict[str, Any]] = {}
    for record_date, values in sorted(latest.items()):
        health: dict[str, Any] = {
            name: _canonical_number(name, item.value.value)
            for name, item in values.items()
        }
        health["source"] = _sources(values.values())
        health_by_date[record_date] = health
    return health_by_date


def daily_energy_expenditure(
    snapshot: dict[str, Any] | None,
    requested_date: str,
    current_date: date,
    *,
    measured: Mapping[str, Any],
    measured_history: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the measured daily calorie components for one local date.

    ``measured`` is the day's entry of ``read_daily_health_by_date`` (an empty
    mapping when the day has none); the total, active and resting energy come
    from it. ``measured_history`` holds ``read_daily_health_by_date`` for the week
    before ``current_date``; the projection reads its resting reference from it.

    Total expenditure is only reported when the provider supplied a total
    directly; active and resting components are not summed to manufacture a
    total. For the running day, a separate derived projection is added (see
    ``_projected_expenditure``).
    """
    if not isinstance(snapshot, dict):
        snapshot = {}
    values: dict[str, float | int | None] = {
        field: None for field in GARMIN_DAILY_EXPENDITURE_FIELDS
    }
    try:
        day = date.fromisoformat(requested_date)
    except ValueError:
        day = None
    is_future = day is None or day > current_date
    _measured_values(measured, is_future, values)
    source = GARMIN_PERFORMANCE_SOURCE
    if any(values[field] is not None for field in values):
        source = str(measured.get("source") or source)
    has_measurement = any(value is not None for value in values.values())
    freshness = _requested_day_freshness(snapshot, requested_date)
    result = {
        **values,
        **_projected_expenditure(snapshot, values, day, current_date, measured_history),
        "source": source if has_measurement else None,
        "measured_date": requested_date if has_measurement else None,
        "freshness": freshness.get("freshness", "unknown"),
        "fetched_at": freshness.get("fetched_at"),
        "synced_at": snapshot.get("synced_at"),
        "provisional": day == current_date,
        "status": "measured" if has_measurement else "unavailable",
    }
    if has_measurement:
        result.update(
            performance_freshness.measurement_age(requested_date, current_date)
        )
    else:
        result.update({"measurement_status": "unknown", "measurement_age_days": None})
    return result


def _requested_day_freshness(
    snapshot: dict[str, Any], requested_date: str
) -> dict[str, Any]:
    source_freshness = snapshot.get("source_freshness")
    freshness = _mapping_value(source_freshness, "daily_stats")
    nutrition_refresh = snapshot.get("nutrition_refresh")
    daily_refresh = _mapping_value(nutrition_refresh, "daily_stats")
    if requested_date in daily_refresh and isinstance(
        daily_refresh[requested_date], dict
    ):
        return daily_refresh[requested_date]
    return freshness


def _mapping_value(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _window_values(
    health_by_date: Mapping[str, Mapping[str, Any]], cutoff: date, end_date: date
) -> tuple[dict[str, list[float]], dict[str, set[str]]]:
    """Collect each daily total and its sources for the days in the window."""
    values: dict[str, list[float]] = {key: [] for key in GARMIN_DAILY_HEALTH_FIELDS}
    sources: dict[str, set[str]] = {key: set() for key in GARMIN_DAILY_HEALTH_FIELDS}
    for record_date, health in health_by_date.items():
        try:
            current = date.fromisoformat(iso_date_prefix(record_date))
        except ValueError:
            continue
        if not cutoff <= current <= end_date:
            continue
        for metric_name, metric_values in values.items():
            number = _as_number(health.get(metric_name))
            if number is not None:
                metric_values.append(float(number))
                if health.get("source"):
                    sources[metric_name].add(str(health["source"]))
    return values, sources


def _window_average(metric_name: str, numbers: list[float]) -> float | int | None:
    """Counts average to whole numbers, energy keeps two decimals."""
    if not numbers:
        return None
    if metric_name in {"steps", "floors"}:
        return round(sum(numbers) / len(numbers))
    return round(sum(numbers) / len(numbers), 2)


def garmin_daily_health_metrics(
    snapshot: dict[str, Any],
    days: int,
    end_date: date,
    current_date: date,
    *,
    health_by_date: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return daily health totals averaged over the requested window.

    ``health_by_date`` holds the canonical totals of ``read_daily_health_by_date``.
    Freshness is sync status and is read from the snapshot.
    """
    values, sources = _window_values(
        health_by_date, end_date - timedelta(days=days - 1), end_date
    )
    units = {
        "steps": "Schritte/Tag",
        "floors": "Stockwerke/Tag",
        "calories": "kcal/Tag",
    }
    result: dict[str, dict[str, Any]] = {}
    for metric_name, numbers in values.items():
        average = _window_average(metric_name, numbers)
        result[f"{metric_name}_7d"] = performance_freshness.garmin_metric_freshness(
            snapshot,
            "daily_stats",
            _metric(
                average,
                units[metric_name],
                ", ".join(sorted(sources[metric_name])) or GARMIN_PERFORMANCE_SOURCE,
                "Durchschnitt der letzten 7 Tage",
            ),
            current_date,
        )
    return result


def _complete_read_windows(snapshot: dict[str, Any]) -> list[tuple[date, date]]:
    """Return the read windows trusted as complete daily-stats reads.

    These are the latest run's window and the window of the day's first, wide
    run, which later one-day runs would otherwise hide.
    """
    freshness = snapshot.get("source_freshness")
    daily_stats = freshness.get("daily_stats") if isinstance(freshness, dict) else None
    if not isinstance(daily_stats, dict) or daily_stats.get("freshness") != "current":
        return []
    provider_sync = snapshot.get("provider_sync")
    if not isinstance(provider_sync, dict):
        return []
    windows: list[tuple[date, date]] = []
    for key in ("read_window", "daily_read_window"):
        window = provider_sync.get(key)
        if not isinstance(window, dict):
            continue
        try:
            windows.append(
                (date.fromisoformat(window["start"]), date.fromisoformat(window["end"]))
            )
        except KeyError, TypeError, ValueError:
            continue
    return windows


def _projection_reference(
    snapshot: dict[str, Any],
    current_date: date,
    measured_history: Mapping[str, Mapping[str, Any]],
) -> tuple[date, float | int] | None:
    """Return the resting calories of the latest complete day within a week.

    Records retained from an earlier sync may still hold a day's running value
    (a partial or failed refresh, or a shorter manual window), so a reference
    must lie inside the window of a fully current daily-stats read. The values
    come from ``measured_history``.
    """
    read_windows = _complete_read_windows(snapshot)
    if not read_windows:
        return None
    reference: tuple[date, float | int] | None = None
    for record_date, values in measured_history.items():
        raw = values.get("resting_kcal")
        try:
            record_day = date.fromisoformat(record_date)
        except ValueError:
            continue
        resting = _as_number(raw)
        if (
            0 < (current_date - record_day).days <= 7
            and any(start <= record_day <= end for start, end in read_windows)
            and resting is not None
            and resting > 0
            and (reference is None or record_day > reference[0])
        ):
            reference = (record_day, resting)
    return reference


def _projected_expenditure(
    snapshot: dict[str, Any],
    values: dict[str, Any],
    day: date | None,
    current_date: date,
    measured_history: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the full-day total for the running day, never presented as Garmin's.

    Garmin's running total only covers the resting calories elapsed so far. The
    projection adds today's active calories to the resting calories of the most
    recent complete day within a week, which is nearly constant per profile.
    """
    projection: dict[str, Any] = {
        "projected_total_kcal": None,
        "projection_resting_kcal": None,
        "projection_reference_date": None,
    }
    active = values["active_kcal"]
    if day != current_date or active is None:
        return projection
    reference = _projection_reference(snapshot, current_date, measured_history)
    if reference is None:
        return projection
    projected = reference[1] + active
    # A reference below what is already measured today is stale or partial.
    if any(
        values[field] is not None and projected < values[field]
        for field in ("resting_kcal", "total_kcal")
    ):
        return projection
    return {
        "projected_total_kcal": projected,
        "projection_resting_kcal": reference[1],
        "projection_reference_date": reference[0].isoformat(),
    }


def _measured_values(
    measured: Mapping[str, Any], is_future: bool, values: dict[str, Any]
) -> None:
    """Set the energy components from the canonical values."""
    for field, name in (
        ("total_kcal", "calories"),
        ("active_kcal", "active_kcal"),
        ("resting_kcal", "resting_kcal"),
    ):
        value = None if is_future else _as_number(measured.get(name))
        values[field] = value if value is not None and value >= 0 else None


def _canonical_number(name: str, value: float) -> float | int | None:
    number = _as_number(value)
    if number is not None and name in {"steps", "floors"}:
        return round(float(number))
    return number


def _sources(observations: Iterable[Observation]) -> str:
    return ", ".join(
        sorted(
            {
                provider_label(item.provenance.provider, SourceView.DAILY_HEALTH)
                for item in observations
                if item.provenance.provider is not None
            }
        )
    )


def _order(item: Observation) -> tuple[bool, float]:
    """Order one day's observations: a timestamped, later record wins."""
    stamp = item.observed_at.timestamp() if item.observed_at is not None else 0.0
    return item.observed_at is not None, stamp
