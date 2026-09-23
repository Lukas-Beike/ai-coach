"""Pure season and competition planning projections."""

from __future__ import annotations

from datetime import date
from typing import Any


def season_plan_summary(
    competitions: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Project season phases for competitions with valid event dates."""
    events: list[dict[str, Any]] = []
    for competition in competitions:
        try:
            event_date = date.fromisoformat(competition["event_date"])
        except (KeyError, TypeError, ValueError):
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
