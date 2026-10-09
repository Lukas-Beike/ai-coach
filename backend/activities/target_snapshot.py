"""Freeze only conservatively matched local targets at detail observation time."""

from typing import Any

from backend.activities.identity import activity_kind
from backend.activities.matching import match_planned_workouts, record_date
from backend.calendar.canonical import canonical_planned_workouts
from backend.planning.workout_text import WorkoutTextError, structured_steps


def freeze_targets(
    local: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    activity_id: str,
    detail: dict[str, Any],
    observed_at: str,
) -> dict[str, Any] | None:
    planned = canonical_planned_workouts([], local, 500)
    matches = match_planned_workouts(planned, activities)
    candidates = [
        (event, row)
        for index, row in matches.items()
        if str(row.get("id")) == activity_id
        for event in [planned[index]]
    ]
    if len(candidates) != 1:
        return None
    event, row = candidates[0]
    matching = _matching_basis(event, row, activities, planned)
    if matching is None:
        return None
    description = str(event.get("description") or "")
    if len(description) > 20000:
        return None
    try:
        steps = structured_steps(description, str(event.get("target") or "AUTO"))
    except WorkoutTextError:
        return None
    if len(steps) > 200:
        return None
    return {
        "steps": steps,
        "basis": {"icu_ftp": detail.get("icu_ftp")},
        "planned_unit_id": event.get("local_id"),
        "observed_at": observed_at,
        "matching": matching,
        "scope": "Local targets observed at first detail refresh; earlier edits cannot be reconstructed.",
    }


def _matching_basis(
    event: dict, row: dict, activities: list[dict], planned: list[dict]
) -> str | None:
    paired = str(row.get("paired_event_id") or "")
    if paired:
        if (
            paired != str(event.get("id"))
            or sum(
                str(item.get("paired_event_id") or "") == paired for item in activities
            )
            != 1
        ):
            return None
        matching = "provider paired_event_id"
    else:
        if not _unique_local_match(row, activities, planned):
            return None
        matching = "unique local date and sport"

    return matching


def _unique_local_match(row: dict, activities: list[dict], planned: list[dict]) -> bool:
    day = record_date(row.get("start_date_local"))
    kind = activity_kind(row)
    if (
        kind == "other"
        or sum(
            record_date(item.get("start_date_local")) == day
            and activity_kind(item) == kind
            for item in activities
        )
        != 1
    ):
        return False
    return (
        sum(
            record_date(item.get("start_date_local")) == day
            and activity_kind(item) == kind
            for item in planned
        )
        == 1
    )
