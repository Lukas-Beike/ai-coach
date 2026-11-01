"""Deterministic training reports with explicit measurement coverage."""

from __future__ import annotations

from collections import defaultdict
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
from backend.canonical.planning_fields import PLANNED_LOAD as PLANNED_LOAD_KEY
from backend.performance.session_rpe_load import session_rpe_load

METHOD = "local-training-report-v1"
_SUMMARY_METRICS = ("moving_duration_s", "distance_m", "training_load")


def _planned_day(row: Mapping[str, Any]) -> str:
    return iso_date_prefix(str(row.get("starts_at_local") or row.get("date") or ""))


def _metric(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    measured = [value for row in rows if (value := number(row.get(key))) is not None]
    return {
        "value": round(sum(measured), 2) if measured else None,
        "measured_sessions": len(measured),
        "total_sessions": len(rows),
    }


def _totals(summaries: Sequence[ActivitySummary]) -> dict[str, Any]:
    result: dict[str, Any] = {"sessions": len(summaries)}
    for key in _SUMMARY_METRICS:
        result[key] = _metric(summaries, key)
    return result


def _weekly_load_history(
    summaries: Sequence[ActivitySummary], today: date, timezone: str
) -> list[dict[str, Any]]:
    monday = today - timedelta(days=today.weekday())
    weeks = []
    for offset in range(7, -1, -1):
        start = monday - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        activities = [
            summary
            for summary in summaries
            if start.isoformat()
            <= summary_local_date(summary, timezone)
            <= min(end, today).isoformat()
        ]
        weeks.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "partial_period": end >= today,
                "training_load": _totals(activities)["training_load"],
            }
        )
    return weeks


def _cumulative_load(
    summaries: Sequence[ActivitySummary], day: date, timezone: str
) -> dict[str, Any]:
    metric = _totals(
        [
            summary
            for summary in summaries
            if summary_local_date(summary, timezone) <= day.isoformat()
        ]
    )["training_load"]
    if not metric["total_sessions"]:
        metric["value"] = 0
    return metric


def zone_distribution(summaries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reports = []
    for sport in sorted({_sport(summary) for summary in summaries}):
        if sport == "strength":
            continue
        sport_rows = [summary for summary in summaries if _sport(summary) == sport]
        duration = sum(number(row.get("moving_duration_s")) or 0 for row in sport_rows)
        for key, sensor in (
            ("power_zone_times", "power"),
            ("heart_rate_zone_times", "heart_rate"),
            ("pace_zone_times", "pace"),
        ):
            zones, measured_sessions = _sensor_zones(sport_rows, key)
            sources = sorted(
                {
                    str(label)
                    for row in sport_rows
                    if _valid_zones(row.get(key))
                    and (label := (row.get("sources") or {}).get(key))
                }
            )
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
                        "source": ", ".join(sources),
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
    activity_summaries: Sequence[ActivitySummary],
    observed_at: str | None = None,
    session_feedback: Mapping[str, Mapping[str, Any]] | None = None,
    computed_at: str | None = None,
) -> dict[str, Any]:
    """Build the report from the activity summaries, one per canonical session.

    ``sport`` is ``"all"`` or a canonical sport. ``observed_at`` is the sync time
    of the summaries (canonical coverage). ``session_feedback`` maps a summary's
    stored key to its session's effective feedback for the session-RPE load.
    """
    end = start + timedelta(days=days - 1)
    effective_end = min(today, end)
    eligible = [
        summary
        for summary in activity_summaries
        if sport == "all" or _sport(summary) == sport
    ]
    current = [
        summary
        for summary in eligible
        if start.isoformat()
        <= summary_local_date(summary, timezone)
        <= effective_end.isoformat()
    ]
    previous_start = start - timedelta(days=days)
    previous = [
        summary
        for summary in eligible
        if previous_start.isoformat()
        <= summary_local_date(summary, timezone)
        < start.isoformat()
    ]
    planned = [
        row
        for row in (plan or {}).get("training_calendar", [])
        if not row.get("is_completed_activity")
        and start.isoformat() <= _planned_day(row) <= effective_end.isoformat()
        and (sport == "all" or str(row.get("sport")) == sport)
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
        "sports": _sport_totals(current),
        "weekly_load": _weekly_load_history(eligible, today, timezone),
        "daily": [
            _daily_report(current, start + timedelta(days=offset), today, timezone)
            for offset in range(days)
        ],
        "zones": zone_distribution(current),
        "session_rpe_load": session_rpe_load(
            current,
            session_feedback or {},
            start=start,
            end=effective_end,
            timezone=timezone,
            computed_at=computed_at,
        ),
        "key_sessions": _key_sessions(current, timezone),
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
            "load": _metric(planned, PLANNED_LOAD_KEY),
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
                "activity_id": summary["id"],
                "date": summary_local_date(summary, timezone),
                "name": str(summary.get("name") or "Training")[:200],
                "notes": str(item.get("notes") or "")[:500],
                "session_rpe": item.get("session_rpe"),
                "deviation_reason": str(item.get("deviation_reason") or "")[:500],
            }
            for summary in current
            for item in (activity_feedback or [])
            if str(item.get("activity_id")) == stored_activity_key(summary)
        ][:100],
        "coverage_note": "Summen enthalten nur bekannte lokale Einträge. Fehlende Belastungen bleiben unbekannt; ein leerer Tag belegt keine Ruhe oder Trainingspause. Die laufende Woche ist nicht mit einer abgeschlossenen Vorwoche vergleichbar.",
    }


def _sport(summary: Mapping[str, Any]) -> str:
    return str(summary.get("sport") or "other")


def _valid_zones(values: Any) -> list[dict]:
    if not isinstance(values, list):
        return []
    return [
        value
        for value in values
        if isinstance(value, dict)
        and number(value.get("secs")) is not None
        and float(value["secs"]) >= 0
        and str(value.get("id", "")).startswith("Z")
    ]


def _sensor_zones(
    sport_rows: Sequence[Mapping[str, Any]], key: str
) -> tuple[dict[str, float], int]:
    zones: dict[str, float] = defaultdict(float)
    measured_sessions = 0
    for row in sport_rows:
        valid = _valid_zones(row.get(key))
        if valid:
            measured_sessions += 1
            for value in valid:
                zones[str(value["id"])[:20]] += float(value["secs"])

    return zones, measured_sessions


def _sport_totals(summaries: Sequence[ActivitySummary]) -> dict[str, Any]:
    return {
        name: _totals([summary for summary in summaries if _sport(summary) == name])
        for name in sorted({_sport(summary) for summary in summaries})
    }


def _key_sessions(
    current: Sequence[ActivitySummary], timezone: str
) -> list[dict[str, Any]]:
    return [
        {
            "activity_id": summary["id"],
            "name": str(summary.get("name") or "Training")[:200],
            "date": summary_local_date(summary, timezone),
            "sport": _sport(summary),
            "training_load": number(summary.get("training_load")),
        }
        for summary in sorted(
            current,
            key=lambda summary: number(summary.get("training_load")) or -1,
            reverse=True,
        )[:3]
    ]


def _daily_report(
    summaries: Sequence[ActivitySummary], day: date, today: date, timezone: str
) -> dict[str, Any]:
    activities = [
        summary
        for summary in summaries
        if summary_local_date(summary, timezone) == day.isoformat()
    ]
    cumulative = {"value": None, "measured_sessions": 0, "total_sessions": 0}
    if day <= today:
        cumulative = _cumulative_load(summaries, day, timezone)
    return {
        "date": day.isoformat(),
        "future": day > today,
        "cumulative_training_load": cumulative,
        "activities": [
            {
                "activity_id": summary["id"],
                "name": str(summary.get("name") or "Training")[:200],
                "sport": _sport(summary),
                "training_load": number(summary.get("training_load")),
            }
            for summary in activities
        ],
        "totals": _totals(activities),
        "sports": _sport_totals(activities),
    }
