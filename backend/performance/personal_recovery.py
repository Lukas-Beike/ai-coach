"""Personal recovery distributions, separated by provider and measurement method.

The comparisons and sleep goal shortfalls read the daily canonical observations of
each provider. Sleep timing variability reads the canonical sleep periods only
(#1419, #1416); without them it has no data.

Segment rule (M2, #1428): within one HRV or resting HR series, a change of the
observation's method, aggregation or measurement context (device model,
firmware, algorithm, sensor, window, protocol) restarts the comparison; only
values since the latest change count. A switch between unknown and known
metadata is a change. Without a reported device model a device change cannot be
seen, so the continuity is unknown.
"""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, tzinfo
from functools import partial
from statistics import median, quantiles
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.canonical.domain_records import SleepPeriod
from backend.canonical.records import Observation
from backend.canonical.sleep_bounds import bounds_fields
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_recovery import CanonicalRecoveryInputs
from backend.performance.display_sources import preferred_providers
from backend.providers.source_labels import SourceView, provider_label

# Each provider's series: (provider, kind) -> (metric, measurement label, scale).
# The measurement is the method, so RMSSD and SDNN form separate,
# never mixed, baselines.
_SERIES: Final = {
    (ProviderId.INTERVALS, MetricKind.SLEEP_DURATION): ("sleep", "duration", 3600),
    (ProviderId.INTERVALS, MetricKind.RESTING_HR): ("resting_hr", "resting", 1),
    (ProviderId.INTERVALS, MetricKind.HRV_RMSSD): ("hrv", "RMSSD", 1),
    (ProviderId.INTERVALS, MetricKind.HRV_SDNN): ("hrv", "SDNN", 1),
    (ProviderId.GARMIN, MetricKind.SLEEP_DURATION): (
        "sleep",
        "duration",
        3600,
    ),
    (ProviderId.GARMIN, MetricKind.RESTING_HR): (
        "resting_hr",
        "resting",
        1,
    ),
    (ProviderId.GARMIN, MetricKind.HRV_RMSSD): (
        "hrv",
        "RMSSD",
        1,
    ),
}


_NOTE: Final = (
    "Quartile vergleichen den letzten Wert mit deinen eigenen früheren Werten. "
    "Die mittleren zwei Quartile enthalten per Definition etwa die Hälfte der "
    "Werte; ein Wert außerhalb ist weder selten noch ein Warnsignal. Keine "
    "Diagnose, keine Trainingsfreigabe und keine Trainingsänderung allein aus "
    "einer Abweichung. Krankheit und Schmerzen separat berücksichtigen. Quellen "
    "und Messfelder werden nicht gemischt. Die Schlafdauer ist eine Schätzung "
    "des jeweiligen Geräts, kein gemessener Schlafbedarf. Der Fehlbetrag zum "
    "Schlafziel summiert nur bekannte Nächte und wird nicht mit längeren Nächten "
    "verrechnet; fehlende Nächte und nicht erfasste Nickerchen begrenzen "
    "diese Aussage. Die Schlafzeit-Streuung ist kein Sleep Regularity Index."
)


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def personal_recovery(
    profile: dict[str, Any],
    today: date,
    *,
    canonical: CanonicalRecoveryInputs | None = None,
) -> dict[str, Any]:
    """Return comparisons, shortfalls and timing variability from ``canonical``."""
    cutoff = (today - timedelta(days=42)).isoformat()
    history_start = (today - timedelta(days=83)).isoformat()
    current_day = today.isoformat()
    groups: dict[tuple[ProviderId, str, str], dict[str, float]] = {}
    contexts: dict[tuple[ProviderId, str, str], dict[str, Observation]] = {}

    add = partial(_add_record, groups, (history_start, current_day))

    if canonical is not None:
        for (provider, kind), (metric, field, scale) in _SERIES.items():
            key = (provider, metric, field)
            daily = canonical.daily_observations(kind, provider)
            for day, observation in sorted(daily.items()):
                add(key, day.isoformat(), observation.value.value, scale)
            if metric != "sleep":
                contexts[key] = {
                    day.isoformat(): observation for day, observation in daily.items()
                }
    baselines = [
        _baseline(key, records, cutoff, today, contexts.get(key, {}))
        for key, records in sorted(groups.items())
    ]
    try:
        target = float(profile.get("sleep_target_hours") or "nan")
    except ValueError, TypeError:
        target = float("nan")
    deficits = _sleep_deficits(groups, target, today)
    regularity = sleep_timing_variability(
        str(profile.get("timezone") or "UTC"),
        today,
        periods=None if canonical is None else canonical.sleep_periods,
    )
    return {
        "method": "personal-quartiles-v1",
        "as_of": current_day,
        "baselines": baselines,
        "sleep_deficits": deficits,
        "sleep_target_hours": target if math.isfinite(target) else None,
        "regularity": regularity,
        "preferred_providers": preferred_providers(),
        "note": _NOTE,
    }


def _add_record(
    groups: dict,
    window: tuple[str, str],
    key: tuple[ProviderId, str, str],
    day: str,
    value: Any,
    scale: float = 1,
) -> None:
    metric = key[1]
    number = _number(value)
    if number is None or number <= 0 or not window[0] <= day <= window[1]:
        return
    number /= scale
    if (
        metric == "sleep"
        and number > 24
        or metric == "resting_hr"
        and not 20 <= number <= 230
    ):
        return
    groups.setdefault(key, {})[day] = number


def _comparability(observation: Observation | None) -> tuple[Any, ...]:
    """Return what must stay equal for two values to share a comparison."""
    if observation is None:
        return ()
    return (
        observation.method,
        observation.aggregation,
        observation.provenance.context,
    )


def _segment_start(
    records: dict[str, float], observations: dict[str, Observation], observed: str
) -> str | None:
    """Return the first day of the latest value's segment, or None without a change."""
    latest = _comparability(observations.get(observed))
    start = None
    for day in sorted(records, reverse=True):
        if _comparability(observations.get(day)) != latest:
            return start
        start = day
    return None


def _window_change(
    records: dict[str, float],
    observations: dict[str, Observation],
    observed: str,
    cutoff: str,
) -> str | None:
    """Return the segment start when it lies inside the comparison window."""
    changed_on = _segment_start(records, observations, observed)
    return changed_on if changed_on is not None and changed_on > cutoff else None


def _reason(*, current: bool, changed: bool) -> str:
    if not current:
        return "Messung veraltet."
    if changed:
        return (
            "Messkontext geändert; mindestens 14 passende Nächte seitdem erforderlich."
        )
    return "Mindestens 14 frühere passende Nächte erforderlich."


def _baseline(
    key: tuple[ProviderId, str, str],
    records: dict[str, float],
    cutoff: str,
    today: date,
    observations: dict[str, Observation],
) -> dict[str, Any]:
    provider, metric, field = key
    observed = max(records)
    changed_on = _window_change(records, observations, observed, cutoff)
    # Today's value never influences its own comparison distribution, and a
    # measurement change restarts it.
    first = changed_on or cutoff
    prior = [value for day, value in records.items() if first <= day < observed]
    latest = records[observed]
    current = observed >= (today - timedelta(days=1)).isoformat()
    baseline: dict[str, Any] = {
        "source": provider_label(provider, SourceView.DAILY_HEALTH),
        "source_provider": provider.value,
        "metric": metric,
        "measurement": field,
        "value": latest,
        "observed_at": observed,
        "window_days": 42,
        "nights": len(prior),
        "unit": {"sleep": "h", "hrv": "ms", "resting_hr": "bpm"}[metric],
        "status": "insufficient_data",
        "history": [
            {"date": day, "value": value} for day, value in sorted(records.items())
        ],
    }
    if observed in observations:
        context = observations[observed].provenance.context.as_details()
        baseline.update(
            measurement_context=context,
            continuity="known" if "device_model" in context else "unknown",
            context_changed_on=changed_on,
        )
    if len(prior) >= 14 and current:
        lower, _, upper = quantiles(prior, n=4, method="inclusive")
        baseline.update(
            status="provisional" if len(prior) < 28 else "ok",
            median=median(prior),
            lower=lower,
            upper=upper,
            position="below" if latest < lower else _upper_position(latest, upper),
        )
    else:
        baseline["reason"] = _reason(current=current, changed=changed_on is not None)

    return baseline


def _upper_position(latest: float, upper: float) -> str:
    return "above" if latest > upper else "within"


def _sleep_deficits(
    groups: dict[tuple[ProviderId, str, str], dict[str, float]],
    target: float,
    today: date,
) -> list[dict[str, Any]]:
    current_day = today.isoformat()
    deficits = []
    if math.isfinite(target) and 4 <= target <= 12:
        for (provider, metric, field), records in sorted(groups.items()):
            if metric != "sleep":
                continue
            selected = {
                day: value
                for day, value in records.items()
                if (today - timedelta(days=6)).isoformat() <= day <= current_day
            }
            deficits.append(
                {
                    "source": provider_label(provider, SourceView.DAILY_HEALTH),
                    "measurement": field,
                    "known_nights": len(selected),
                    "target_hours": target,
                    "deficit_hours": round(
                        sum(max(0, target - value) for value in selected.values()), 2
                    ),
                    "status": "ok" if len(selected) == 7 else "partial",
                }
            )

    return deficits


def sleep_timing_variability(
    timezone_name: str,
    today: date,
    *,
    periods: Sequence[SleepPeriod] | None = None,
) -> dict[str, Any]:
    """Summarize clock-time deviations of actual sleep intervals, without a score.

    Compares onset and wake with the athlete's own earlier nights; this is not the
    Sleep Regularity Index. Version 2 (#1429) reports no median and no deviation
    below 14 earlier intervals; otherwise it equals version 1.

    ``periods`` are the canonical sleep periods; None means the serving source
    stores none, and there is no data. Each provider and field pair is kept
    apart, an interval is dated by its end in the profile zone and the latest
    interval of a day is kept.
    """
    try:
        zone: tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError, ValueError:
        zone = UTC
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for source, item in _period_items(periods or (), zone, today):
        groups.setdefault((source, item["method"]), {})[item["date"]] = item
    series = []
    for (source, method), records in sorted(groups.items()):
        series.append(_sleep_series(source, method, records, today))
    if not series:
        reason = "Keine geprüften datierten Schlafbeginn- und Endzeiten verfügbar."
        return {
            "method": "sleep-timing-variability-v2",
            "timezone": timezone_name,
            "status": "insufficient_data",
            "reason": reason,
            "unknown_reason": reason,
            "series": [],
            "sources": [],
            "coverage": {"baseline_nights": 0, "required_nights": 14},
            "points_14": [],
            "points_84": [],
        }
    rank = {"insufficient_data": 0, "provisional": 1, "ok": 2}
    return {
        "method": "sleep-timing-variability-v2",
        "timezone": timezone_name,
        "status": max(
            (item["status"] for item in series), key=lambda status: rank[status]
        ),
        "series": series,
        "sources": series,
        "points_14": [point for item in series for point in item["points_14"]],
        "points_84": [point for item in series for point in item["points_84"]],
        "coverage": {
            "baseline_nights": sum(
                item["coverage"]["baseline_nights"] for item in series
            ),
            "required_nights": 14,
        },
    }


_PERIOD_SOURCES: Final = {
    ProviderId.INTERVALS: "Intervals.icu",
    ProviderId.GARMIN: "Garmin Connect",
}


def _interval_item(
    start: datetime, end: datetime, method: str, zone: tzinfo, today: date
) -> dict[str, Any] | None:
    """Describe one interval in the profile zone, or None outside the 84 days."""
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    if not today - timedelta(days=83) <= local_end.date() <= today:
        return None
    return {
        "method": method,
        "date": local_end.date().isoformat(),
        "onset_at": local_start.isoformat(),
        "wake_at": local_end.isoformat(),
        "onset_at_utc": start.isoformat(),
        "wake_at_utc": end.isoformat(),
        "duration_hours": round((end - start).total_seconds() / 3600, 3),
        "onset_minutes_local": local_start.hour * 60 + local_start.minute,
        "wake_minutes_local": local_end.hour * 60 + local_end.minute,
    }


def _period_items(
    periods: Sequence[SleepPeriod], zone: tzinfo, today: date
) -> list[tuple[str, dict[str, Any]]]:
    """Describe canonical periods as the legacy intervals, oldest start first."""
    items: list[tuple[str, dict[str, Any]]] = []
    for period in sorted(periods, key=lambda period: period.start):
        provider = period.provenance.provider
        source = None if provider is None else _PERIOD_SOURCES.get(provider)
        fields = bounds_fields(period.bounds_method or "")
        if source is None or fields is None:
            continue
        item = _interval_item(period.start, period.end, "/".join(fields), zone, today)
        if item is not None:
            items.append((source, item))
    return items


def _circular_median(values: list[float]) -> float:
    return min(
        values,
        key=lambda candidate: sum(
            abs((value - candidate + 720) % 1440 - 720) for value in values
        ),
    )


def _circular_deviation(value: float, center: float | None) -> float | None:
    return (
        None if center is None else round(abs((value - center + 720) % 1440 - 720), 1)
    )


def _sleep_series(
    source: str, method: str, records: dict[str, dict[str, Any]], today: date
) -> dict[str, Any]:
    ordered = [records[key] for key in sorted(records)]
    latest = ordered[-1]
    prior = [
        item
        for item in ordered
        if (today - timedelta(days=42)).isoformat() <= item["date"] < latest["date"]
    ]
    count = len(prior)
    status = "insufficient_data"
    if count >= 14:
        status = "provisional"
    if count >= 28:
        status = "ok"
    reason = None
    if count < 14:
        reason = "Mindestens 14 frühere datierte Schlafintervalle erforderlich."
    if not count:
        reason = "Keine geprüften datierten Schlafbeginn- und Endzeiten verfügbar."
    # v2: below 14 earlier intervals there is no reference, so no deviation.
    compared = status != "insufficient_data"
    onset = (
        _circular_median([item["onset_minutes_local"] for item in prior])
        if compared
        else None
    )
    wake = (
        _circular_median([item["wake_minutes_local"] for item in prior])
        if compared
        else None
    )
    points = [
        {
            **item,
            "source": source,
            "method": method,
            "onset_deviation_minutes": _circular_deviation(
                item["onset_minutes_local"], onset
            ),
            "wake_deviation_minutes": _circular_deviation(
                item["wake_minutes_local"], wake
            ),
        }
        for item in ordered
    ]
    by_date = {item["date"]: item for item in points}

    def display(
        days: int, *, _by_date=by_date, _source=source, _method=method
    ) -> list[dict[str, Any]]:
        first = today - timedelta(days=days - 1)
        result = []
        for offset in range(days):
            day = first + timedelta(days=offset)
            result.append(
                _by_date.get(day.isoformat())
                or {
                    "date": day.isoformat(),
                    "source": _source,
                    "method": _method,
                    "observed_at": None,
                    "onset_at": None,
                    "wake_at": None,
                    "duration_hours": None,
                    "onset_deviation_minutes": None,
                    "wake_deviation_minutes": None,
                }
            )
        return result

    onset_dev = [
        item["onset_deviation_minutes"]
        for item in points
        if item["onset_deviation_minutes"] is not None
    ]
    wake_dev = [
        item["wake_deviation_minutes"]
        for item in points
        if item["wake_deviation_minutes"] is not None
    ]
    return {
        "source": source,
        "method": method,
        "status": status,
        "reason": reason,
        "unknown_reason": reason,
        "coverage": {
            "baseline_nights": count,
            "valid_nights_42_days": count,
            "required_nights": 14,
            "provisional_until_nights": 27,
        },
        "source_observed_at": latest["wake_at_utc"],
        "observed_at": latest["wake_at_utc"],
        "baseline": {
            "onset_median_minutes_local": onset,
            "wake_median_minutes_local": wake,
            "onset_deviation_median_minutes": median(onset_dev) if compared else None,
            "wake_deviation_median_minutes": median(wake_dev) if compared else None,
        },
        "points": points,
        "points_14": display(14),
        "points_84": display(84),
    }
