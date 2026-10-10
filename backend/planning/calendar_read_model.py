"""Pure projection of the local planning calendar read model."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.activities import calendar_projection, grouping
from backend.activities.workout_profile import planned_profile
from backend.athlete.local_date import iso_date_prefix
from backend.calendar import canonical, local
from backend.planning import adaptive
from backend.planning import calendar as planning_calendar
from backend.planning.conflicts import calendar_items_share_local_day
from backend.weather import history


def _competition_priority(competition: dict[str, Any]) -> str:
    priority = str(competition.get("priority") or "").strip().upper()
    if priority not in {"A", "B", "C"}:
        priority = (
            str(competition.get("category") or "").strip().upper().removeprefix("RACE_")
        )
    return priority if priority in {"A", "B", "C"} else ""


def _competition_conflict_codes(
    unit_day: str, unit: dict[str, Any], competitions: list[Any]
) -> list[str]:
    """Hard units conflict with A/B races (race day and the day before) and C races (race day)."""
    if not unit_day or not adaptive.workout_is_hard(unit):
        return []
    codes: list[str] = []
    for competition in competitions:
        if not isinstance(competition, dict):
            continue
        event_day = iso_date_prefix(str(competition.get("event_date") or ""))
        try:
            day_before = (date.fromisoformat(event_day) - timedelta(days=1)).isoformat()
        except ValueError:
            continue
        priority = _competition_priority(competition)
        if priority in {"A", "B"} and unit_day in {event_day, day_before}:
            codes.append(planning_calendar.COMPETITION_AB_CONFLICT)
        elif priority == "C" and unit_day == event_day:
            codes.append(planning_calendar.COMPETITION_C_CONFLICT)
    return codes


def _marker_conflict_reasons(
    unit: dict[str, Any], external_events: list[Any]
) -> list[str]:
    reasons: list[str] = []
    for event in external_events:
        if not isinstance(event, dict) or not any(
            event.get(reason) for reason in planning_calendar.MARKER_LABELS
        ):
            continue
        if not calendar_items_share_local_day(unit, event):
            continue
        decision = planning_calendar.calendar_constraint_decision(unit, event)
        if decision and decision["reason"] not in reasons:
            reasons.append(decision["reason"])
    return reasons


def planned_unit_conflicts(
    unit: dict[str, Any], external_events: list[Any], competitions: list[Any]
) -> list[dict[str, str]]:
    """Read-only calendar conflicts for one planned unit, using planning rules."""
    if unit.get("archived") or unit.get("local_deleted"):
        return []
    unit_day = iso_date_prefix(
        str(unit.get("date") or unit.get("start_date_local") or "")
    )
    codes = [
        *_marker_conflict_reasons(unit, external_events),
        *_competition_conflict_codes(unit_day, unit, competitions),
    ]
    labels = {
        **planning_calendar.MARKER_LABELS,
        **planning_calendar.COMPETITION_CONFLICT_LABELS,
    }
    return [{"code": code, "label": labels[code]} for code in dict.fromkeys(codes)]


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
    weather_planned = [
        {**row, "workout_profile": profile}
        if (profile := planned_profile(row))
        else row
        for row in weather_planned
    ]
    weather_planned = [
        {
            **row,
            "conflicts": planned_unit_conflicts(row, external_events, competitions),
        }
        for row in weather_planned
    ]
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
