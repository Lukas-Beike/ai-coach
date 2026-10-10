"""Map iCalendar provider DTOs to local training constraints."""

from __future__ import annotations

from typing import Any

from backend.calendar.markers import has_marker

ICAL_NO_TRAINING_MARKER = "[NO_TRAINING]"
ICAL_NO_INTENSITY_MARKER = "[NO_INTENSITY]"
ICAL_SHORT_ONLY_MARKER = "[SHORT_ONLY]"
ICAL_TRAINING_MARKERS = (
    ICAL_NO_TRAINING_MARKER,
    ICAL_NO_INTENSITY_MARKER,
    ICAL_SHORT_ONLY_MARKER,
)


def _ical_description_contains(description: Any, marker: str) -> bool:
    return has_marker(description, marker)


def _ical_marker_text(description: Any, name: Any = "") -> str:
    return f"{name or ''} {description or ''}"


def ical_training_impact(description: Any, name: Any = "") -> bool:
    text = _ical_marker_text(description, name)
    return any(
        _ical_description_contains(text, marker) for marker in ICAL_TRAINING_MARKERS
    )


def ical_training_relevant(description: Any, name: Any = "") -> bool:
    description_text = str(description or "").strip()
    marker_text = _ical_marker_text(description, name)
    return bool(description_text) and not _ical_description_contains(
        marker_text, ICAL_NO_TRAINING_MARKER
    )


def ical_no_intensity(description: Any, name: Any = "") -> bool:
    return _ical_description_contains(
        _ical_marker_text(description, name), ICAL_NO_INTENSITY_MARKER
    )


def ical_short_only(description: Any, name: Any = "") -> bool:
    return _ical_description_contains(
        _ical_marker_text(description, name), ICAL_SHORT_ONLY_MARKER
    )


def calendar_event_constraints(event: dict[str, Any]) -> dict[str, Any]:
    description = event.get("description")
    name = event.get("name")
    return {
        **{key: value for key, value in event.items() if key != "description"},
        "training_impact": ical_training_impact(description, name),
        "training_relevant": ical_training_relevant(description, name),
        "no_training": has_marker(
            _ical_marker_text(description, name), ICAL_NO_TRAINING_MARKER
        ),
        "no_intensity": ical_no_intensity(description, name),
        "short_only": ical_short_only(description, name),
    }
