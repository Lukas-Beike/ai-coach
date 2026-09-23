"""Pure projection of the local planning calendar read model."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.activities import calendar_projection, grouping
from backend.calendar import canonical, local
from backend.weather import history


def project_planning_calendar(
    local_planned: list[Any],
    activities: list[Any],
    weather: Any,
    competitions: list[Any],
    external_events: list[Any],
    *,
    today: date,
    provider_window: Any,
    default_name: str,
) -> dict[str, Any]:
    """Project supplied planning data into the six calendar read models."""
    canonical_planned = canonical.canonical_planned_workouts([], local_planned)
    compliance_planned, planning_compliance = (
        calendar_projection.planning_compliance_state(
            canonical_planned, activities, today
        )
    )
    weather_planned = history.add_to_planned(
        compliance_planned, weather, default_name=default_name
    )
    return {
        "planned": weather_planned,
        "training_calendar": calendar_projection.training_calendar_items(
            weather_planned, activities
        ),
        "calendar": local.local_calendar_events(
            compliance_planned, competitions, external_events
        ),
        "planning_view": {
            "source": "local",
            "local_count": len(compliance_planned),
            "remote_count": 0,
            "items": weather_planned,
            "provider_window": provider_window,
        },
        "planning_compliance": planning_compliance,
        "parallel_cycling": grouping.parallel_cycling_event_groups(compliance_planned),
    }
