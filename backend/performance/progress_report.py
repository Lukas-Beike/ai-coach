"""Weekly progress projection per sport over 4 to 12 ISO weeks (read time only).

Descriptive aggregation of local records: no training model, no judgement. A
week without records or the running week is incomplete or unknown, never rest.
The 3-zone split approximates the polarized 3-zone model from the zone times a
provider recorded for each session (power first, else heart rate); it never
recalculates zones from current thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import (
    ActivitySummary,
    stored_activity_key,
    summary_local_date,
)
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import ProviderId
from backend.performance import eftp
from backend.performance.session_rpe_load import session_load
from backend.performance.training_report import metric_sum, valid_zones
from backend.providers.source_labels import SourceView, provider_label

METHOD = "weekly-progress-v1"
SPORT_BUCKETS = ("run", "ride", "strength")
# First zone number of the moderate and of the high band, by the number of zones
# the provider recorded: 6 or more (Coggan power, Intervals.icu 7-zone heart rate)
# or up to 5 (5-zone heart rate).
ZONE_BANDS = {"many": (3, 5), "five": (3, 4)}
ZONE_MAPPING = (
    "Approximation of the 3-zone model from provider zone times: with 6 or more "
    "zones Z1-Z2 low, Z3-Z4 moderate, Z5+ high; with up to 5 zones Z1-Z2 low, Z3 "
    "moderate, Z4+ high. Per session power zones, else heart-rate zones; pace "
    "zones unused."
)
PROFILE_DURATIONS = (60, 300, 1200)
# CTL and eFTP come from Intervals.icu wellness days and ride summaries.
INTERVALS_SOURCE = provider_label(ProviderId.INTERVALS, SourceView.BODY_HISTORY)
# Wellness-day eFTP, else the day's latest Intervals.icu ride summary.
EFTP_SOURCE = provider_label(ProviderId.INTERVALS, SourceView.CURRENT_METRIC)


def _sport(summary: Mapping[str, Any]) -> str:
    return str(summary.get("sport") or "other")


def _zone_number(zone_id: str) -> int | None:
    digits = zone_id[1:]
    return int(digits) if digits.isdigit() else None


def _band(zone: int | None, zone_count: int) -> str | None:
    if zone is None:
        return None
    moderate, high = ZONE_BANDS["many" if zone_count >= 6 else "five"]
    return "low" if zone < moderate else "moderate" if zone < high else "high"


def _intensity(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = {"low": 0.0, "moderate": 0.0, "high": 0.0}
    sensors: set[str] = set()
    measured = 0
    for row in sessions:
        for sensor, key in (
            ("power", "power_zone_times"),
            ("heart_rate", "heart_rate_zone_times"),
        ):
            zones = [
                (_zone_number(str(zone["id"])), float(zone["secs"]))
                for zone in valid_zones(row.get(key))
            ]
            count = max((number or 0 for number, _ in zones), default=0)
            bands = [
                (band, secs)
                for number, secs in zones
                if (band := _band(number, count)) is not None
            ]
            if bands:
                measured += 1
                sensors.add(sensor)
                for band, secs in bands:
                    seconds[band] += secs
                break
    return {
        "seconds": {k: round(v) for k, v in seconds.items()} if measured else None,
        "sensors": sorted(sensors),
        "measured_sessions": measured,
        "total_sessions": len(sessions),
    }


def _load(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = metric_sum(sessions, "training_load")
    result["source"] = ", ".join(
        sorted(
            {
                str(label)
                for row in sessions
                if number(row.get("training_load")) is not None
                and (label := (row.get("sources") or {}).get("training_load"))
            }
        )
    )
    return result


def _rpe(
    sessions: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    timezone: str,
) -> dict[str, Any]:
    values = [
        session_load(row, feedback.get(stored_activity_key(row)), timezone)[1]
        for row in sessions
    ]
    known = [value for value in values if value is not None]
    return {
        "value": round(sum(known), 1) if known else None,
        "unit": "AU",
        "rated_sessions": len(known),
        "total_sessions": len(values),
    }


def _plan(
    plan: Mapping[str, Any] | None, start: date, end: date, sport: str
) -> dict[str, Any]:
    if plan is None:
        return {"available": False}
    planned = [
        row
        for row in plan.get("training_calendar", [])
        if not row.get("is_completed_activity")
        and start.isoformat()
        <= iso_date_prefix(str(row.get("starts_at_local") or row.get("date") or ""))
        <= end.isoformat()
        and (sport == "all" or str(row.get("sport")) == sport)
    ]
    return {
        "available": True,
        "planned": len(planned),
        "completed": sum(
            bool(row.get("compliance", {}).get("actual_activity")) for row in planned
        ),
        "missed": sum(
            row.get("compliance", {}).get("status") == "missed" for row in planned
        ),
    }


def _bucket(
    sessions: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    plan: Mapping[str, Any] | None,
    week: tuple[date, date],
    sport: str,
    timezone: str,
) -> dict[str, Any]:
    return {
        "sessions": len(sessions),
        "duration_s": metric_sum(sessions, "moving_duration_s"),
        "training_load": _load(sessions),
        "session_rpe_load": _rpe(sessions, feedback, timezone),
        "intensity_3zone": _intensity(sessions),
        "plan": _plan(plan, week[0], week[1], sport),
    }


def _first_last(values: Mapping[Any, float]) -> dict[str, Any]:
    if not values:
        return {"status": "insufficient_data", "observations": 0}
    days = sorted(values)
    first, last = days[0], days[-1]
    return {
        "status": "ok" if first != last else "insufficient_data",
        "first": {"date": str(first), "value": values[first]},
        "last": {"date": str(last), "value": values[last]},
        "change": round(values[last] - values[first], 2) if first != last else None,
        "observations": len(values),
    }


# sport -> (record profile key, curve key, point value field, output unit)
_CURVES = {
    "ride": ("power_profile", "duration_curve", "watts", "watts"),
    "run": ("running_profile", "speed", "speed_mps", "speed_mps"),
}


def _mean_max_change(
    records: Sequence[Mapping[str, Any]], start: date, middle: date, end: date
) -> dict[str, Any]:
    """Best ride power and run speed per duration and environment: earlier versus later half.

    Indoor and outdoor sessions are compared separately, as in the power profile,
    so a change of environment never reads as a change of fitness.
    """
    halves = {"earlier": (start, middle - timedelta(days=1)), "later": (middle, end)}
    result: dict[str, Any] = {
        "method": "Best full-resolution stream value per duration and environment; later half minus earlier half.",
    }
    for sport, (profile_key, curve_key, field, unit) in _CURVES.items():
        result[sport] = {
            environment: _environment_change(
                [
                    row
                    for row in records
                    if row.get("sport") == sport
                    and row.get("environment") == environment
                ],
                halves,
                (profile_key, curve_key, field, unit),
            )
            for environment in ("outdoor", "indoor")
        }
    return result


def _environment_change(
    records: Sequence[Mapping[str, Any]],
    halves: Mapping[str, tuple[date, date]],
    curve: tuple[str, str, str, str],
) -> dict[str, Any]:
    profile_key, curve_key, field, unit = curve
    best: dict[str, dict[int, float]] = {}
    sources: set[str] = set()
    periods = {}
    for name, (first, last) in halves.items():
        rows = [
            row
            for row in records
            if first.isoformat() <= str(row.get("date") or "") <= last.isoformat()
        ]
        usable = [
            row for row in rows if (row.get(profile_key) or {}).get("status") == "ok"
        ]
        periods[name] = {
            "start": first.isoformat(),
            "end": last.isoformat(),
            "records": len(rows),
            "usable_records": len(usable),
        }
        best[name] = {}
        for row in usable:
            profile = row[profile_key]
            if profile.get("source"):
                sources.add(str(profile["source"]))
            for point in profile.get(curve_key, []):
                value, seconds = (
                    number(point.get(field)),
                    point.get("duration_seconds"),
                )
                if (
                    value is not None
                    and seconds in PROFILE_DURATIONS
                    and value > best[name].get(seconds, -1.0)
                ):
                    best[name][seconds] = value
    durations = []
    for seconds in PROFILE_DURATIONS:
        early, late = best["earlier"].get(seconds), best["later"].get(seconds)
        durations.append(
            {
                "duration_seconds": seconds,
                f"earlier_{unit}": early,
                f"later_{unit}": late,
                f"change_{unit}": None
                if early is None or late is None
                else round(late - early, 3),
            }
        )
    return {
        "unit": unit,
        "source": ", ".join(sorted(sources)),
        "periods": periods,
        "durations": durations,
    }


def _mean_max_window(
    records: Sequence[Mapping[str, Any]] | None,
    start: date,
    middle: date,
    end: date,
    weeks: int,
    sport: str,
) -> dict[str, Any]:
    if weeks < 2:
        return {"status": "insufficient_data"}
    if records is None:
        return {"status": "outside_curve_window"}
    result = _mean_max_change(records, start, middle, end)
    if sport != "all":
        result = {
            key: value
            for key, value in result.items()
            if key not in _CURVES or key == sport
        }
    return result


def weekly_progress(
    *,
    start: date,
    weeks: int,
    today: date,
    sport: str,
    timezone: str,
    activity_summaries: Sequence[ActivitySummary],
    session_feedback: Mapping[str, Mapping[str, Any]] | None = None,
    plan: Mapping[str, Any] | None = None,
    ctl_by_day: Mapping[date, float] | None = None,
    eftp_by_day: Mapping[date, float] | None = None,
    curve_records: Sequence[Mapping[str, Any]] | None = (),
    observed_at: str | None = None,
) -> dict[str, Any]:
    """``start`` is a Monday; ``sport`` is ``"all"`` or a canonical sport."""
    end = start + timedelta(days=7 * weeks - 1)
    effective_end = min(end, today)
    eligible = [
        row for row in activity_summaries if sport == "all" or _sport(row) == sport
    ]
    names = ("all", *SPORT_BUCKETS) if sport == "all" else (sport,)
    feedback = session_feedback or {}
    week_rows = []
    for index in range(weeks):
        first = start + timedelta(weeks=index)
        last = first + timedelta(days=6)
        week: dict[str, Any] = {
            "week_start": first.isoformat(),
            "week_end": last.isoformat(),
        }
        if first > today:
            week_rows.append({**week, "status": "future"})
            continue
        sessions = [
            row
            for row in eligible
            if first.isoformat()
            <= summary_local_date(row, timezone)
            <= min(last, today).isoformat()
        ]
        if not sessions:
            week_rows.append(
                {
                    **week,
                    "status": "incomplete_current_week_no_records"
                    if last >= today
                    else "no_records_unknown",
                    "plan": _plan(plan, first, min(last, today), sport),
                }
            )
            continue
        span = (first, min(last, today))
        week_rows.append(
            {
                **week,
                "status": "incomplete_current_week" if last >= today else "recorded",
                "sports": {
                    name: _bucket(
                        sessions
                        if name == "all" or sport != "all"
                        else [row for row in sessions if _sport(row) == name],
                        feedback,
                        plan,
                        span,
                        sport if sport != "all" else name,
                        timezone,
                    )
                    for name in names
                },
            }
        )
    in_window = [
        row
        for row in activity_summaries
        if start.isoformat()
        <= summary_local_date(row, timezone)
        <= effective_end.isoformat()
    ]
    middle = start + timedelta(weeks=weeks // 2)
    ctl = _first_last(
        {
            day: value
            for day, value in (ctl_by_day or {}).items()
            if start <= day <= effective_end
        }
    )
    eftp_values = eftp.eftp_daily_values(eftp_by_day, in_window, start, effective_end)
    return {
        "method": METHOD,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weeks": weeks,
        "timezone": timezone,
        "sport": sport,
        "effective_end": effective_end.isoformat(),
        "observed_at": observed_at,
        "zone_mapping": ZONE_MAPPING,
        "week_list": week_rows,
        "ctl": {**ctl, "source": INTERVALS_SOURCE},
        **(
            {
                "eftp": {
                    "sport": "ride",
                    "source": EFTP_SOURCE,
                    **_first_last(eftp_values),
                }
            }
            if sport in {"all", "ride"}
            else {}
        ),
        **(
            {
                "mean_max_power": _mean_max_window(
                    curve_records, start, middle, effective_end, weeks, sport
                )
            }
            if sport in {"all", "ride", "run"}
            else {}
        ),
        "coverage_note": "Aggregation of known local records. A week without records is unknown, not rest; the running week is incomplete. Missing loads, RPE and zone times stay unknown; AU, TSS-like load and zone seconds are never combined. No training model is applied.",
    }
