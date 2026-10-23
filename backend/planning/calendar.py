"""Pure projections for calendar conflicts during local planning."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.calendar.markers import has_marker
from backend.providers.intervals_workouts import WORKOUT_INTERVALS_FIELD

_HARD_KEYWORD_PATTERN = re.compile(
    r"\b(intervals?|vo2(max)?|threshold|tempo|sprints?|race|tabata|hiit|hard|sweet\s*spot)\b"
)
_HARD_PERCENT_PATTERN = re.compile(r"\b(9\d|[1-9]\d{2})%", re.ASCII)
# [NO_INTENSITY] and rest classification stay conservative: a named zone from Z2 up is not easy.
_HARD_EFFORT_PATTERNS = (
    _HARD_KEYWORD_PATTERN,
    re.compile(r"\bz(one)?\s*[2-9]\b"),
    _HARD_PERCENT_PATTERN,
)
# Race-proximity conflicts treat zone 2 endurance as easy; only Z3+ counts as hard.
_RACE_HARD_EFFORT_PATTERNS = (
    _HARD_KEYWORD_PATTERN,
    re.compile(r"\bz(one)?\s*[3-9]\b"),
    _HARD_PERCENT_PATTERN,
)
_EASY_EFFORT_PATTERN = re.compile(
    r"\b(?:easy|recovery|regeneration|locker|ruhetag|z1|zone\s*1)\b"
)


def _effort_text(workout: dict[str, Any]) -> str:
    return (
        f"{workout.get('name', '')} {workout.get('description', '')} "
        f"{workout.get('target', '')} "
        f"{workout.get('steps', '')} {workout.get(WORKOUT_INTERVALS_FIELD, '')} "
        f"{workout.get('workout_steps', '')}"
    ).casefold()


def workout_is_hard_effort(workout: dict[str, Any]) -> bool:
    """Return whether name, description, targets or steps name race-relevant hard effort."""
    text = _effort_text(workout)
    return any(pattern.search(text) for pattern in _RACE_HARD_EFFORT_PATTERNS)


def workout_is_explicitly_easy(workout: dict[str, Any]) -> bool:
    """Return whether a workout explicitly opts into easy effort."""
    text = _effort_text(workout)
    if any(pattern.search(text) for pattern in _HARD_EFFORT_PATTERNS):
        return False
    return bool(_EASY_EFFORT_PATTERN.search(text))


def workout_is_rest(workout: dict[str, Any]) -> bool:
    text = f"{workout.get('name', '')} {workout.get('description', '')}".casefold()
    if any(pattern.search(text) for pattern in _HARD_EFFORT_PATTERNS):
        return False
    if any(
        workout.get(key) not in (None, "", [], {})
        for key in ("steps", WORKOUT_INTERVALS_FIELD, "distance", "distance_meters")
    ):
        return False
    duration = workout.get("duration_minutes")
    if duration in (None, "") and workout.get("moving_time") not in (None, ""):
        try:
            duration = float(workout["moving_time"]) / 60
        except TypeError, ValueError:
            duration = None
    try:
        if duration not in (None, "") and float(duration) <= 0:
            return True
    except TypeError, ValueError:
        pass
    if duration not in (None, ""):
        return False
    return bool(re.search(r"\b(?:rest|ruhetag|sportpause)\b", text))


SHORT_ONLY_MAX_MINUTES = 60
NO_TRAINING_MARKER = "[NO_TRAINING]"
NO_INTENSITY_MARKER = "[NO_INTENSITY]"
SHORT_ONLY_MARKER = "[SHORT_ONLY]"
_MARKER_BY_REASON = {
    "no_training": NO_TRAINING_MARKER,
    "no_intensity": NO_INTENSITY_MARKER,
    "short_only": SHORT_ONLY_MARKER,
}


def _workout_minutes(workout: dict[str, Any]) -> float | None:
    for key, factor in (("duration_minutes", 1), ("moving_time", 1 / 60)):
        value = workout.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value) * factor
        except TypeError, ValueError:
            return None
    return None


def calendar_event_has_constraint(event: dict[str, Any], reason: str) -> bool:
    """Return whether an event sets one constraint flag or names its marker."""
    marker_text = f"{event.get('name', '')} {event.get('description', '')}".casefold()
    return bool(event.get(reason)) or has_marker(marker_text, _MARKER_BY_REASON[reason])


def calendar_constraint_decision(
    workout: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any] | None:
    """Centralize external event constraints used by every planning mutation."""
    no_training = calendar_event_has_constraint(event, "no_training")
    no_intensity = calendar_event_has_constraint(event, "no_intensity")
    short_only = calendar_event_has_constraint(event, "short_only")
    if no_training and not workout_is_rest(workout):
        return {
            "blocked": True,
            "reason": "no_training",
            "marker": NO_TRAINING_MARKER,
        }
    if no_intensity and not workout_is_explicitly_easy(workout):
        return {
            "blocked": True,
            "reason": "no_intensity",
            "marker": NO_INTENSITY_MARKER,
        }
    minutes = _workout_minutes(workout)
    if short_only and minutes is not None and minutes > SHORT_ONLY_MAX_MINUTES:
        return {
            "blocked": True,
            "reason": "short_only",
            "marker": SHORT_ONLY_MARKER,
        }
    return None


def adaptive_change_calendar_blocked(
    change: dict[str, Any], blockers: list[dict[str, Any]]
) -> bool:
    """Return whether current calendar blockers reject one adaptive change.

    A kept replacement must pass every marker of its day. An archive is
    calendar-bound only when it rested on a [NO_TRAINING] event that still blocks.
    """
    payload = change.get("payload")
    if not isinstance(payload, dict) or not payload.get("archived"):
        return bool(blockers)
    no_training = [
        event
        for event in change.get("external_events") or []
        if isinstance(event, dict) and event.get("no_training")
    ]
    if "calendar" not in (change.get("blocking_triggers") or []) or not no_training:
        return False
    original_ids = {str(event["id"]) for event in no_training if event.get("id")}
    return not any(
        blocker.get("reason") == "no_training"
        and str(blocker.get("id") or "") in original_ids
        for blocker in blockers
    )


MARKER_LABELS = {
    "no_training": "Kein Training",
    "no_intensity": "Keine Intensität",
    "short_only": "Nur kurze Einheiten",
}
_REASON_BY_MARKER = {
    NO_TRAINING_MARKER: "no_training",
    NO_INTENSITY_MARKER: "no_intensity",
    SHORT_ONLY_MARKER: "short_only",
}
COMPETITION_AB_CONFLICT = "competition_ab"
COMPETITION_C_CONFLICT = "competition_c"
COMPETITION_CONFLICT_LABELS = {
    COMPETITION_AB_CONFLICT: "Hartes Training am Vortag oder am Tag eines A/B-Wettkampfs",
    COMPETITION_C_CONFLICT: "Hartes Training am Tag eines C-Wettkampfs",
}


def marker_label(reason: Any) -> str:
    return MARKER_LABELS.get(str(reason or ""), "Kalenderbeschränkung")


def marker_conflict_message(day: Any, conflicts: list[dict[str, Any]]) -> str:
    """Name the planned day and the first blocking calendar marker."""
    first = conflicts[0] if conflicts else {}
    reason = first.get("reason") or _REASON_BY_MARKER.get(
        str(first.get("constraint") or "")
    )
    iso_day = iso_date_prefix(str(day or first.get("date") or ""))
    return (
        f"Am {_german_date(iso_day)} ist „{marker_label(reason)}“ eingetragen. "
        "Die lokale Einheit verletzt diese Kalenderbeschränkung."
    )


def _german_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.day:02d}.{parsed.month:02d}.{parsed.year}"
