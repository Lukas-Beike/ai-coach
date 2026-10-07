"""Deterministic training reports with explicit measurement coverage."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.activities.duplicates import (
    deduplicate_api_records,
    intervals_cycling_activities_match,
)
from backend.activities.identity import intervals_activity_device_source

METHOD = "local-training-report-v1"


def number(value: Any) -> float | None:
    if type(value) not in {float, int} or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def canonical_rows(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    raw = (snapshot.get("raw_provider_data") or {}).get("activities")
    rows = raw if isinstance(raw, list) else snapshot.get("recent_activities", [])
    rows = [row for row in deduplicate_api_records(rows or []) if isinstance(row, dict)]
    wahoo = [row for row in rows if intervals_activity_device_source(row) == "wahoo"]
    kept = [
        row
        for row in rows
        if not (
            intervals_activity_device_source(row) == "garmin"
            and any(intervals_cycling_activities_match(other, row) for other in wahoo)
        )
    ]
    return kept, len(rows) - len(kept)


def activity_day(row: dict[str, Any], timezone: str = "UTC") -> str:
    absolute = row.get("start_date")
    if absolute:
        try:
            started = datetime.fromisoformat(str(absolute).replace("Z", "+00:00"))
            if started.tzinfo is not None:
                return started.astimezone(ZoneInfo(timezone)).date().isoformat()
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return str(row.get("start_date_local") or row.get("date") or "")[:10]


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"sessions": len(rows)}
    for key in ("moving_time", "distance", "icu_training_load"):
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
                "training_load": _totals(activities)["icu_training_load"],
            }
        )
    return weeks


def _cumulative_load(
    rows: list[dict[str, Any]], day: date, timezone: str
) -> dict[str, Any]:
    metric = _totals(
        [row for row in rows if activity_day(row, timezone) <= day.isoformat()]
    )["icu_training_load"]
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
            ("icu_zone_times", "power"),
            ("icu_hr_zone_times", "heart_rate"),
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
    snapshot: dict[str, Any] | None,
    *,
    start: date,
    days: int,
    today: date,
    sport: str = "all",
    plan: dict[str, Any] | None = None,
    checkins: list[dict[str, Any]] | None = None,
    activity_feedback: list[dict[str, Any]] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    snapshot = snapshot or {}
    rows, duplicates = canonical_rows(snapshot)
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
        <= str(row.get("checkin_date") or row.get("date") or "")[:10]
        <= effective_end.isoformat()
    ]
    return {
        "method": METHOD,
        "source": "Intervals.icu + local planning/check-ins",
        "observed_at": snapshot.get("synced_at"),
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
            "load": _totals(planned)["icu_training_load"],
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
            "training_load": number(row.get("icu_training_load")),
        }
        for row in sorted(
            current,
            key=lambda row: number(row.get("icu_training_load")) or -1,
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
                "training_load": number(row.get("icu_training_load")),
            }
            for row in activities
        ],
        "totals": _totals(activities),
        "sports": _sport_totals(activities),
    }
