"""Deterministic training reports with explicit measurement coverage."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.activities.duplicates import (
    deduplicate_api_records,
    intervals_cycling_activities_match,
)
from backend.activities.identity import activity_datetime
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import RecordingOrigin
from backend.providers import intervals_performance_fields as intervals_perf_fields
from backend.providers.intervals_activity_fields import (
    intervals_activity_device_source,
    intervals_activity_recorded_by_wahoo,
)

METHOD = "local-training-report-v1"


def deduplicated_rows(rows: Sequence[Any]) -> tuple[list[dict[str, Any]], int]:
    """Drop duplicate rows and Garmin rows that a matching Wahoo row duplicates.

    Returns the kept rows and how many rows were dropped.
    """
    unique = [
        row for row in deduplicate_api_records(list(rows)) if isinstance(row, dict)
    ]
    wahoo = [row for row in unique if intervals_activity_recorded_by_wahoo(row)]
    indexed = sorted(
        (started, index)
        for index, row in enumerate(wahoo)
        if (
            started := activity_datetime(
                row.get("start_date_local") or row.get("start_date")
            )
        )
        is not None
    )
    starts = [started for started, _ in indexed]
    window = timedelta(minutes=30)

    def matches_wahoo(row: dict[str, Any]) -> bool:
        started = activity_datetime(
            row.get("start_date_local") or row.get("start_date")
        )
        if started is None:
            return False
        minimum = datetime.min.replace(tzinfo=started.tzinfo)
        maximum = datetime.max.replace(tzinfo=started.tzinfo)
        low = bisect_left(
            starts,
            started - window if started >= minimum + window else minimum,
        )
        high = bisect_right(
            starts,
            started + window if started <= maximum - window else maximum,
        )
        return any(
            intervals_cycling_activities_match(wahoo[index], row)
            for _, index in indexed[low:high]
        )

    kept = [
        row
        for row in unique
        if not (
            intervals_activity_device_source(row) == RecordingOrigin.GARMIN
            and matches_wahoo(row)
        )
    ]
    return kept, len(unique) - len(kept)


def activity_day(row: dict[str, Any], timezone: str = "UTC") -> str:
    absolute = row.get("start_date")
    if absolute:
        try:
            started = datetime.fromisoformat(str(absolute))
            if started.tzinfo is not None:
                return started.astimezone(ZoneInfo(timezone)).date().isoformat()
        except ValueError, ZoneInfoNotFoundError:
            pass
    return iso_date_prefix(str(row.get("start_date_local") or row.get("date") or ""))


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"sessions": len(rows)}
    for key in ("moving_time", "distance", intervals_perf_fields.TRAINING_LOAD):
        measured = [
            value for row in rows if (value := number(row.get(key))) is not None
        ]
        result[key] = {
            "value": round(sum(measured), 2) if measured else None,
            "measured_sessions": len(measured),
            "total_sessions": len(rows),
        }
    return result


def _weekly_load_history(
    rows: list[dict[str, Any]], today: date, timezone: str
) -> list[dict[str, Any]]:
    monday = today - timedelta(days=today.weekday())
    weeks = []
    for offset in range(7, -1, -1):
        start = monday - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        activities = [
            row
            for row in rows
            if start.isoformat()
            <= activity_day(row, timezone)
            <= min(end, today).isoformat()
        ]
        weeks.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "partial_period": end >= today,
                "training_load": _totals(activities)[
                    intervals_perf_fields.TRAINING_LOAD
                ],
            }
        )
    return weeks


def _cumulative_load(
    rows: list[dict[str, Any]], day: date, timezone: str
) -> dict[str, Any]:
    metric = _totals(
        [row for row in rows if activity_day(row, timezone) <= day.isoformat()]
    )[intervals_perf_fields.TRAINING_LOAD]
    if not metric["total_sessions"]:
        metric["value"] = 0
    return metric


def zone_distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports = []
    for sport in sorted({str(row.get("type") or "Unknown") for row in rows}):
        if sport in {"WeightTraining", "StrengthTraining"}:
            continue
        sport_rows = [row for row in rows if str(row.get("type") or "Unknown") == sport]
        duration = sum(number(row.get("moving_time")) or 0 for row in sport_rows)
        for key, sensor in (
            (intervals_perf_fields.ZONE_TIMES, "power"),
            (intervals_perf_fields.HEART_RATE_ZONE_TIMES, "heart_rate"),
            ("pace_zone_times", "pace"),
        ):
            zones, measured_sessions = _sensor_zones(sport_rows, key, sensor)
            if zones:
                reports.append(
                    {
                        "sport": sport,
                        "sensor": sensor,
                        "seconds": dict(zones),
                        "measured_seconds": sum(zones.values()),
                        "training_seconds": duration,
                        "measured_sessions": measured_sessions,
                        "total_sessions": len(sport_rows),
                        "source": "Intervals.icu",
                        "method": "Provider zones recorded for each activity; no recalculation using current thresholds",
                    }
                )
    return reports


def training_report(
    *,
    start: date,
    days: int,
    today: date,
    sport: str = "all",
    plan: dict[str, Any] | None = None,
    checkins: list[dict[str, Any]] | None = None,
    activity_feedback: list[dict[str, Any]] | None = None,
    timezone: str = "UTC",
    activity_rows: Sequence[Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build the report from the raw rows of the activity reader.

    ``observed_at`` is the sync time of those rows (canonical coverage).
    """
    rows, duplicates = deduplicated_rows(activity_rows)
    end = start + timedelta(days=days - 1)
    effective_end = min(today, end)
    eligible = [row for row in rows if sport == "all" or str(row.get("type")) == sport]
    current = [
        row
        for row in eligible
        if start.isoformat() <= activity_day(row, timezone) <= effective_end.isoformat()
    ]
    previous_start = start - timedelta(days=days)
    previous = [
        row
        for row in eligible
        if previous_start.isoformat() <= activity_day(row, timezone) < start.isoformat()
    ]
    sports = _sport_totals(current)
    refs = _key_sessions(current, timezone)
    planned = [
        row
        for row in (plan or {}).get("training_calendar", [])
        if not row.get("is_completed_activity")
        and start.isoformat() <= activity_day(row) <= effective_end.isoformat()
        and (sport == "all" or str(row.get("type") or row.get("sport")) == sport)
    ]
    feedback = [
        row
        for row in (checkins or [])
        if start.isoformat()
        <= iso_date_prefix(str(row.get("checkin_date") or row.get("date") or ""))
        <= effective_end.isoformat()
    ]
    return {
        "method": METHOD,
        "source": "Intervals.icu + local planning/check-ins",
        "observed_at": observed_at,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "timezone": timezone,
        "sport": sport,
        "partial_period": end >= today,
        "effective_end": effective_end.isoformat(),
        "totals": _totals(current),
        "previous": {
            "start": previous_start.isoformat(),
            "end": (start - timedelta(days=1)).isoformat(),
            "totals": _totals(previous),
        },
        "sports": sports,
        "weekly_load": _weekly_load_history(eligible, today, timezone),
        "daily": [
            _daily_report(current, start + timedelta(days=offset), today, timezone)
            for offset in range(days)
        ],
        "zones": zone_distribution(current),
        "key_sessions": refs,
        "excluded_duplicates": duplicates,
        "planning": {
            "available": plan is not None,
            "sessions": len(planned),
            "completed": sum(
                bool(row.get("compliance", {}).get("actual_activity"))
                for row in planned
            ),
            "missed": sum(
                row.get("compliance", {}).get("status") == "missed" for row in planned
            ),
            "load": _totals(planned)[intervals_perf_fields.TRAINING_LOAD],
        },
        "checkins": [
            {
                "date": row.get("checkin_date") or row.get("date"),
                "illness": row.get("illness"),
                "pain": row.get("pain"),
                "notes": str(row.get("notes") or "")[:400],
            }
            for row in feedback
        ],
        "activity_feedback": [
            {
                "activity_id": str(activity["id"]),
                "date": activity_day(activity, timezone),
                "name": str(activity.get("name") or "Training")[:200],
                "notes": str(item.get("notes") or "")[:500],
                "session_rpe": item.get("session_rpe"),
                "deviation_reason": str(item.get("deviation_reason") or "")[:500],
            }
            for activity in current
            for item in (activity_feedback or [])
            if str(item.get("activity_id")) == str(activity.get("id"))
        ][:100],
        "coverage_note": "Summen enthalten nur bekannte lokale Einträge. Fehlende Belastungen bleiben unbekannt; ein leerer Tag belegt keine Ruhe oder Trainingspause. Die laufende Woche ist nicht mit einer abgeschlossenen Vorwoche vergleichbar.",
    }


def _valid_zones(values: Any, sensor: str) -> list[dict]:
    if not isinstance(values, list):
        return []
    normalized = [
        {"id": f"Z{index + 1}", "secs": value}
        if sensor == "heart_rate" and number(value) is not None
        else value
        for index, value in enumerate(values)
    ]
    valid = [
        value
        for value in normalized
        if isinstance(value, dict)
        and number(value.get("secs")) is not None
        and float(value["secs"]) >= 0
        and str(value.get("id", "")).startswith("Z")
    ]

    return valid


def _sensor_zones(
    sport_rows: list[dict], key: str, sensor: str
) -> tuple[dict[str, float], int]:
    zones: dict[str, float] = defaultdict(float)
    measured_sessions = 0
    for row in sport_rows:
        valid = _valid_zones(row.get(key), sensor)
        if valid:
            measured_sessions += 1
            for value in valid:
                zones[str(value["id"])[:20]] += float(value["secs"])

    return zones, measured_sessions


def _sport_totals(rows: list[dict]) -> dict[str, Any]:
    sports = {
        name: _totals(
            [row for row in rows if str(row.get("type") or "Unknown") == name]
        )
        for name in sorted({str(row.get("type") or "Unknown") for row in rows})
    }

    return sports


def _key_sessions(current: list[dict], timezone: str) -> list[dict]:
    refs = [
        {
            "activity_id": str(row.get("id") or ""),
            "name": str(row.get("name") or "Training")[:200],
            "date": activity_day(row, timezone),
            "sport": row.get("type"),
            "training_load": number(row.get(intervals_perf_fields.TRAINING_LOAD)),
        }
        for row in sorted(
            current,
            key=lambda row: number(row.get(intervals_perf_fields.TRAINING_LOAD)) or -1,
            reverse=True,
        )[:3]
    ]

    return refs


def _daily_report(
    rows: list[dict], day: date, today: date, timezone: str
) -> dict[str, Any]:
    activities = [row for row in rows if activity_day(row, timezone) == day.isoformat()]
    cumulative = {"value": None, "measured_sessions": 0, "total_sessions": 0}
    if day <= today:
        cumulative = _cumulative_load(rows, day, timezone)
    return {
        "date": day.isoformat(),
        "future": day > today,
        "cumulative_training_load": cumulative,
        "activities": [
            {
                "activity_id": str(row.get("id") or ""),
                "name": str(row.get("name") or "Training")[:200],
                "sport": str(row.get("type") or "Unknown"),
                "training_load": number(row.get(intervals_perf_fields.TRAINING_LOAD)),
            }
            for row in activities
        ],
        "totals": _totals(activities),
        "sports": _sport_totals(activities),
    }
