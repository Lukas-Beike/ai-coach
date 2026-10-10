"""Pure projections for calendar conflicts during local planning."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.calendar.markers import has_marker

_HARD_EFFORT_PATTERNS = (
    re.compile(
        r"\b(intervals?|vo2(max)?|threshold|tempo|sprints?|race|tabata|hiit|hard|sweet\s*spot)\b"
    ),
    re.compile(r"\bz(one)?\s*[2-9]\b"),
    re.compile(r"\b(9\d|[1-9]\d{2})%", re.ASCII),
)
_EASY_EFFORT_PATTERN = re.compile(
    r"\b(?:easy|recovery|regeneration|locker|ruhetag|z1|zone\s*1)\b"
)


def workout_is_explicitly_easy(workout: dict[str, Any]) -> bool:
    """Return whether a workout explicitly opts into easy effort."""
    text = (
        f"{workout.get('name', '')} {workout.get('description', '')} "
        f"{workout.get('target', '')} "
        f"{workout.get('steps', '')} {workout.get('intervals', '')} "
        f"{workout.get('workout_steps', '')}"
    ).casefold()
    if any(pattern.search(text) for pattern in _HARD_EFFORT_PATTERNS):
        return False
    return bool(_EASY_EFFORT_PATTERN.search(text))


def workout_is_rest(workout: dict[str, Any]) -> bool:
    text = f"{workout.get('name', '')} {workout.get('description', '')}".casefold()
    if any(pattern.search(text) for pattern in _HARD_EFFORT_PATTERNS):
        return False
    if any(
        workout.get(key) not in (None, "", [], {})
        for key in ("steps", "intervals", "distance", "distance_meters")
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


def calendar_constraint_decision(
    workout: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any] | None:
    """Centralize external event constraints used by every planning mutation."""
    marker_text = f"{event.get('name', '')} {event.get('description', '')}".casefold()
    no_training = bool(event.get("no_training")) or has_marker(
        marker_text, NO_TRAINING_MARKER
    )
    no_intensity = bool(event.get("no_intensity")) or has_marker(
        marker_text, NO_INTENSITY_MARKER
    )
    short_only = bool(event.get("short_only")) or has_marker(
        marker_text, SHORT_ONLY_MARKER
    )
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
