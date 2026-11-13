"""Season evidence from the recorded activities before a competition."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import (
    ActivitySummary,
    stored_activity_key,
    summary_is_indoor,
    summary_local_date,
)
from backend.athlete.measurements import number
from backend.canonical.stored_sports import resolve_competition_sport
from backend.canonical.vocabulary import Environment
from backend.planning.running_week import week_start as _week_start
from backend.planning.season import season_plan_summary
from backend.providers.source_labels import SESSION_SOURCES_LABEL

ActivitySummariesBetween = Callable[[date, date], Sequence[ActivitySummary]]


ACTIVITY_SOURCE = f"{SESSION_SOURCES_LABEL} recorded activities"
PREPARATION_WEEKS = 12


def season_preparation(
    competitions: list[dict[str, Any]],
    today: date,
    timezone: str = "UTC",
    observations: list[dict[str, Any]] | None = None,
    *,
    activity_summaries: ActivitySummariesBetween,
) -> dict[str, Any]:
    """Summarise the preparation evidence of every season event.

    ``activity_summaries`` returns the activity summaries around the given
    inclusive local dates; it is called once for the span of all event windows.
    """
    result = season_plan_summary(competitions, today)
    windows = [_evidence_window(event, today) for event in result["events"]]
    rows = (
        list(
            activity_summaries(
                min(start for start, _ in windows), max(end for _, end in windows)
            )
        )
        if windows
        else []
    )
    for event, (window_start, window_end) in zip(result["events"], windows):
        sport = _competition_sport(event)
        indoor = _competition_indoor(event)
        eligible = [
            row
            for row in rows
            if row.get("sport") == sport
            and summary_is_indoor(row) == indoor
            and window_start.isoformat()
            <= summary_local_date(row, timezone)
            <= window_end.isoformat()
        ]
        longest = sorted(
            [row for row in eligible if number(row.get("moving_duration_s"))],
            key=lambda row: number(row.get("moving_duration_s")) or -1,
            reverse=True,
        )[:3]
        weeks = _preparation_weeks(eligible, window_start, timezone)
        analyses = {row["activity_id"]: row for row in (observations or [])}
        target_context = _target_context(event)
        event["preparation"] = {
            "status": "observations" if eligible else "insufficient_data",
            "sport": sport,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "sessions_84_days": len(eligible),
            "weeks": weeks,
            "weeks_with_recorded_training": sum(
                bool(week["sessions"]) for week in weeks
            ),
            "target_context": _target_context(event),
            "weekly_observed_volume": _weekly_volume(weeks),
            "long_session_evidence": _long_session_evidence(longest),
            "target_distance_comparison": _target_distance_comparison(
                target_context, longest
            ),
            "specificity_evidence": _specificity_evidence(eligible, analyses),
            "source_counts": {
                ACTIVITY_SOURCE: len(eligible),
                "cached activity analyses": len(
                    [row for row in eligible if stored_activity_key(row) in analyses]
                ),
            },
            "long_sessions": [
                {
                    "activity_id": row["id"],
                    "date": summary_local_date(row, timezone),
                    "duration_seconds": number(row.get("moving_duration_s")),
                    "distance_meters": number(row.get("distance_m")),
                    "name": str(row.get("name") or "Training")[:200],
                    "aerobic": (analyses.get(stored_activity_key(row)) or {}).get(
                        "aerobic"
                    ),
                }
                for row in longest
            ],
            "note": "Calendar phase and observed preparation are separate. Distance, terrain, intensity and fueling rehearsal require explicit evidence; no race-time or readiness score.",
        }
    return {
        **result,
        "method": "season-observed-training-v1",
        "timezone": timezone,
    }


def _competition_sport(event: dict[str, Any]) -> str | None:
    """Return the canonical sport of a supported competition, else None."""
    stored = resolve_competition_sport(event.get("sport"), event.get("environment"))
    return None if stored is None else stored.sport.value


def _competition_indoor(event: dict[str, Any]) -> bool:
    """Return True when the competition is indoor or virtual."""
    stored = resolve_competition_sport(event.get("sport"), event.get("environment"))
    return stored is not None and stored.environment in {
        Environment.INDOOR,
        Environment.VIRTUAL,
    }


def _target_context(event: dict[str, Any]) -> dict[str, Any]:
    raw = str(event.get("distance") or "").strip().lower()
    distance = None
    try:
        value = float(raw.replace(",", ".").replace("km", "").replace("m", "").strip())
        if "km" in raw:
            distance = value * 1000
        elif raw.endswith("m") or value >= 100:
            distance = value
    except ValueError:
        pass
    target = str(event.get("target") or "").strip()
    return {
        "sport": _competition_sport(event),
        "distance_meters": int(distance)
        if distance is not None and distance.is_integer()
        else distance,
        "distance_confirmed": distance is not None,
        "target": target or None,
        "target_confirmed": bool(target),
        "source": "confirmed local competition",
    }


def _weekly_volume(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "observations"
        if any(week["sessions"] for week in weeks)
        else "insufficient_data",
        "weeks_with_sessions": sum(bool(week["sessions"]) for week in weeks),
        "weeks_total": len(weeks),
        "sessions": sum(week["sessions"] for week in weeks),
        "duration_seconds": sum(week["duration_seconds"] or 0 for week in weeks)
        or None,
        "duration_known_sessions": sum(
            week["duration_known_sessions"] for week in weeks
        ),
        "distance_meters": sum(week["distance_meters"] or 0 for week in weeks) or None,
        "distance_known_sessions": sum(
            week["distance_known_sessions"] for week in weeks
        ),
        "source": ACTIVITY_SOURCE,
    }


def _long_session_evidence(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [
        value
        for row in sessions
        if (value := number(row.get("moving_duration_s"))) is not None
    ]
    distances = [
        value
        for row in sessions
        if (value := number(row.get("distance_m"))) is not None
    ]
    return {
        "status": "observations" if sessions else "insufficient_data",
        "sessions": len(sessions),
        "duration_seconds": max(durations) if durations else None,
        "duration_known_sessions": len(durations),
        "distance_meters": max(distances) if distances else None,
        "distance_known_sessions": len(distances),
        "source": ACTIVITY_SOURCE,
    }


def _target_distance_comparison(
    target_context: dict[str, Any], sessions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    target = target_context.get("distance_meters")
    distances = [
        value
        for row in sessions
        if (value := number(row.get("distance_m"))) is not None
    ]
    if target is None or not distances:
        return {
            "status": "unknown",
            "target_distance_meters": target,
            "observed_long_session_distance_meters": max(distances)
            if distances
            else None,
            "source": "confirmed competition and recorded activities",
        }
    return {
        "status": "observed",
        "target_distance_meters": target,
        "observed_long_session_distance_meters": max(distances),
        "source": "confirmed competition and recorded activities",
    }


def _specificity_evidence(
    eligible: Sequence[Mapping[str, Any]], analyses: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    cached = [
        analyses[stored_activity_key(row)]
        for row in eligible
        if stored_activity_key(row) in analyses
    ]
    return {
        "status": "observations" if cached else "insufficient_data",
        "cached_analyses": len(cached),
        "known_dimensions": {
            key: sum((item.get(key) or {}).get("status") == "ok" for item in cached)
            for key in ("aerobic", "power_profile", "interval_quality")
        },
        "source": "cached activity analyses",
    }


def _evidence_window(event: dict[str, Any], today: date) -> tuple[date, date]:
    """Return the 12 Monday-Sunday weeks of evidence before the competition.

    Evidence ends at the event date for completed competitions and at today
    for future ones, so a past race is judged by its own preparation.
    """
    window_end = min(today, date.fromisoformat(event["event_date"]))
    window_start = _week_start(window_end) - timedelta(weeks=PREPARATION_WEEKS - 1)
    return window_start, window_end


def _preparation_weeks(
    eligible: Sequence[Mapping[str, Any]], window_start: date, timezone: str
) -> list[dict]:
    weeks = []
    for offset in range(PREPARATION_WEEKS):
        start = window_start + timedelta(weeks=offset)
        end = start + timedelta(days=6)
        measured = [
            row
            for row in eligible
            if start.isoformat() <= summary_local_date(row, timezone) <= end.isoformat()
        ]
        durations = [
            value
            for row in measured
            if (value := number(row.get("moving_duration_s"))) is not None
        ]
        distances = [
            value
            for row in measured
            if (value := number(row.get("distance_m"))) is not None
        ]
        weeks.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "sessions": len(measured),
                "duration_seconds": sum(durations) if durations else None,
                "duration_known_sessions": len(durations),
                "distance_meters": sum(distances) if distances else None,
                "distance_known_sessions": len(distances),
            }
        )

    return weeks
