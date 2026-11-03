"""Pure season and competition planning projections."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix


def season_plan_summary(
    competitions: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Project season phases for competitions with valid event dates."""
    events: list[dict[str, Any]] = []
    for competition in competitions:
        try:
            event_date = date.fromisoformat(competition["event_date"])
        except KeyError, TypeError, ValueError:
            continue

        days = (event_date - today).days
        if days < 0:
            phase = "completed"
        elif days <= 14:
            phase = "taper"
        elif days <= 42:
            phase = "peak"
        elif days <= 84:
            phase = "build"
        else:
            phase = "base"
        events.append({**competition, "days_until": days, "phase": phase})

    events.sort(key=lambda item: (item["event_date"], item["priority"], item["name"]))
    return {
        "as_of": today.isoformat(),
        "events": events,
        "next_event": next(
            (event for event in events if event["days_until"] >= 0), None
        ),
    }


TARGET_PRIORITIES = frozenset({"A", "B"})
TRANSITION_DAYS = 28
PHASE_BOUNDARIES = (
    "Phase by days to the race: base over 84, build 43-84, peak 15-42, taper 0-14."
)


def target_phase(competitions: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Season phase toward the next A/B race; read-only, derived from dates.

    ``transition`` follows an A/B race of the last 28 days when no later one is
    planned; without any such race the phase is ``unknown``.
    """
    targets = [
        {
            **row,
            "priority": str(row.get("priority") or "B"),
            "name": str(row.get("name") or ""),
            "event_date": iso_date_prefix(row.get("event_date")),
        }
        for row in competitions
        if str(row.get("priority") or "B") in TARGET_PRIORITIES
    ]
    events = season_plan_summary(targets, today)["events"]
    upcoming = next((e for e in events if e["days_until"] >= 0), None)
    if upcoming is not None:
        return {
            "phase": upcoming["phase"],
            "weeks_to_race": upcoming["days_until"] // 7,
            "days_to_race": upcoming["days_until"],
            "race": {
                "date": upcoming["event_date"],
                "name": str(upcoming.get("name") or "")[:120],
                "priority": upcoming.get("priority"),
            },
        }
    recent = bool(events) and events[-1]["days_until"] >= -TRANSITION_DAYS
    return {"phase": "transition" if recent else "unknown"}


def planning_state(
    competitions: list[dict[str, Any]],
    today: date,
    latest_replan: dict[str, Any] | None,
    adaptive_status: dict[str, Any],
) -> dict[str, Any]:
    """Combine preloaded planning values without mutating their inputs."""
    return {
        "season": season_plan_summary(competitions, today),
        "latest_replan": latest_replan,
        **adaptive_status,
    }
