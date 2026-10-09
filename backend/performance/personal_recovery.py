"""Personal recovery distributions, separated by provider and measurement field."""

import math
from datetime import date, timedelta, timezone, tzinfo
from functools import partial
from statistics import median, quantiles
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.athlete.local_date import iso_date_prefix
from backend.performance.morning_battery import timestamp
from backend.performance.recovery import (
    dated_garmin_recovery_records,
    garmin_recovery_metric,
)


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


INTERVALS_SOURCE = "Intervals.icu"


def personal_recovery(
    wellness: list[dict[str, Any]],
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    cutoff = (today - timedelta(days=42)).isoformat()
    history_start = (today - timedelta(days=83)).isoformat()
    current_day = today.isoformat()
    groups: dict[tuple[str, str, str], dict[str, float]] = {}

    add = partial(_add_record, groups, (history_start, current_day))

    for row in wellness:
        day = iso_date_prefix(str(row.get("id") or row.get("date") or ""))
        add((INTERVALS_SOURCE, "sleep", "sleepSecs"), day, row.get("sleepSecs"), 3600)
        add((INTERVALS_SOURCE, "resting_hr", "restingHR"), day, row.get("restingHR"))
        # Unknown HRV measurement methods cannot support a homogeneous baseline.
        if row.get("hrv_method") in {"RMSSD", "SDNN"}:
            add((INTERVALS_SOURCE, "hrv", str(row["hrv_method"])), day, row.get("hrv"))
    _add_garmin_records(garmin, history_start, current_day, add)
    baselines = [
        _baseline(key, records, cutoff, today)
        for key, records in sorted(groups.items())
    ]
    try:
        target = float(profile.get("sleep_target_hours") or "nan")
    except ValueError, TypeError:
        target = float("nan")
    deficits = _sleep_deficits(groups, target, today)
    regularity = sleep_regularity(
        wellness, garmin, str(profile.get("timezone") or "UTC"), today
    )
    return {
        "method": "personal-quartiles-v1",
        "as_of": current_day,
        "baselines": baselines,
        "sleep_deficits": deficits,
        "sleep_target_hours": target if math.isfinite(target) else None,
        "regularity": regularity,
        "note": "Persönliche Quartile beschreiben Abweichungen, keine medizinische Trainingsfreigabe. Krankheit und Schmerzen separat berücksichtigen. Quellen und Messfelder werden nicht gemischt; lange Nächte gleichen Defizite nicht rechnerisch aus.",
    }


def _add_record(
    groups: dict,
    window: tuple[str, str],
    key: tuple[str, str, str],
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


def _baseline(
    key: tuple[str, str, str], records: dict[str, float], cutoff: str, today: date
) -> dict[str, Any]:
    source, metric, field = key
    observed = max(records)
    # Today's value never influences its own normal range.
    prior = [value for day, value in records.items() if cutoff <= day < observed]
    latest = records[observed]
    current = observed >= (today - timedelta(days=1)).isoformat()
    baseline: dict[str, Any] = {
        "source": source,
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
        baseline["reason"] = (
            "Messung veraltet."
            if not current
            else "Mindestens 14 frühere passende Nächte erforderlich."
        )

    return baseline


def _upper_position(latest: float, upper: float) -> str:
    return "above" if latest > upper else "within"


def _sleep_deficits(groups: dict, target: float, today: date) -> list[dict[str, Any]]:
    current_day = today.isoformat()
    deficits = []
    if math.isfinite(target) and 4 <= target <= 12:
        for (source, metric, field), records in sorted(groups.items()):
            if metric != "sleep":
                continue
            selected = {
                day: value
                for day, value in records.items()
                if (today - timedelta(days=6)).isoformat() <= day <= current_day
            }
            deficits.append(
                {
                    "source": source,
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


def _add_garmin_records(
    garmin: dict, history_start: str, current_day: str, add: Any
) -> None:
    specifications = (
        ("sleep", "sleep", "sleepTimeSeconds", 3600),
        ("resting_hr", "resting_hr", "restingHeartRate", 1),
        ("hrv", "hrv", "lastNightAvg", 1),
    )
    for section, metric, field, scale in specifications:
        for day, record in sorted(
            dated_garmin_recovery_records(garmin.get(section)), key=lambda item: item[0]
        ):
            if not history_start <= day <= current_day:
                continue
            value, observed = garmin_recovery_metric(
                {section: [record]}, section, (field,)
            )
            if observed == day:
                add(("Garmin Connect", metric, field), day, value, scale)


_SLEEP_START_FIELDS = (
    "sleepStartTimestampGMT",
    "sleepStartTimestamp",
    "sleep_start_at",
    "sleepStart",
    "sleep_start",
    "onset_at",
)
_SLEEP_END_FIELDS = (
    "sleepEndTimestampGMT",
    "sleepEndTimestamp",
    "sleep_end_at",
    "sleepEnd",
    "sleep_end",
    "wake_at",
)


def sleep_regularity(
    wellness: list[dict[str, Any]],
    garmin: dict[str, Any],
    timezone_name: str,
    today: date,
) -> dict[str, Any]:
    """Summarize actual sleep intervals without turning them into a score."""
    try:
        zone: tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError, ValueError:
        zone = timezone.utc
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in wellness:
        for item in _sleep_intervals(row, zone, today):
            groups.setdefault(("Intervals.icu", item["method"]), {})[item["date"]] = (
                item
            )
    for item in _sleep_intervals(garmin.get("sleep"), zone, today):
        groups.setdefault(("Garmin Connect", item["method"]), {})[item["date"]] = item
    series = []
    for (source, method), records in sorted(groups.items()):
        series.append(_sleep_series(source, method, records, today))
    if not series:
        reason = "Keine geprueften datierten Schlafbeginn- und Endzeiten verfuegbar."
        return {
            "method": "sleep-regularity-v1",
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
        "method": "sleep-regularity-v1",
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


def _sleep_intervals(payload: Any, zone: Any, today: date) -> list[dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    pending, visited = [payload], 0
    while pending and visited < 2000:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            sf = next(
                (
                    key
                    for key in _SLEEP_START_FIELDS
                    if current.get(key) not in (None, "")
                ),
                "unknown",
            )
            ef = next(
                (
                    key
                    for key in _SLEEP_END_FIELDS
                    if current.get(key) not in (None, "")
                ),
                "unknown",
            )
            start, end = timestamp(current.get(sf)), timestamp(current.get(ef))
            if (
                start is not None
                and end is not None
                and timedelta(0) < end - start <= timedelta(hours=24)
            ):
                local_start, local_end = start.astimezone(zone), end.astimezone(zone)
                if today - timedelta(days=83) <= local_end.date() <= today:
                    result[(start.isoformat(), end.isoformat())] = {
                        "method": f"{sf}/{ef}",
                        "date": local_end.date().isoformat(),
                        "onset_at": local_start.isoformat(),
                        "wake_at": local_end.isoformat(),
                        "onset_at_utc": start.isoformat(),
                        "wake_at_utc": end.isoformat(),
                        "duration_hours": round(
                            (end - start).total_seconds() / 3600, 3
                        ),
                        "onset_minutes_local": local_start.hour * 60
                        + local_start.minute,
                        "wake_minutes_local": local_end.hour * 60 + local_end.minute,
                    }
            pending.extend(
                value for value in current.values() if isinstance(value, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(current[:500])
    return list(result.values())


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
        reason = "Mindestens 14 fruehere datierte Schlafintervalle erforderlich."
    if not count:
        reason = "Keine geprueften datierten Schlafbeginn- und Endzeiten verfuegbar."
    onset = (
        _circular_median([item["onset_minutes_local"] for item in prior])
        if prior
        else None
    )
    wake = (
        _circular_median([item["wake_minutes_local"] for item in prior])
        if prior
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
            "onset_deviation_median_minutes": median(onset_dev) if prior else None,
            "wake_deviation_median_minutes": median(wake_dev) if prior else None,
        },
        "points": points,
        "points_14": display(14),
        "points_84": display(84),
    }
