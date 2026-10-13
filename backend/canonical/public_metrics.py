"""Neutral metric names for the activity and calendar JSON shown in the browser.

Stored activity rows and planned workouts keep the metric keys of the provider
that reported them. The browser contract names those metrics neutrally, so the
HTTP layer translates stored keys through this module instead of exposing them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Stored key -> neutral key. The stored key is removed from the translated copy.
_NEUTRAL_METRIC_KEYS = (
    ("icu_training_load", "training_load"),
    ("icu_intensity", "intensity"),
    ("icu_rpe", "rpe"),
)


def neutral_activity_metrics(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with stored metric keys renamed neutrally.

    An existing neutral value wins over the stored one. Records without the
    stored metrics are returned unchanged.
    """
    translated = dict(record)
    for stored_key, neutral_key in _NEUTRAL_METRIC_KEYS:
        if stored_key not in translated:
            continue
        stored = translated.pop(stored_key)
        if translated.get(neutral_key) is None:
            translated[neutral_key] = stored
    return translated


def neutral_calendar_entry(entry: Any) -> Any:
    """Translate one calendar entry and the activity matched to it."""
    if not isinstance(entry, Mapping):
        return entry
    translated = neutral_activity_metrics(entry)
    compliance = translated.get("compliance")
    if isinstance(compliance, Mapping) and isinstance(
        compliance.get("actual_activity"), Mapping
    ):
        translated["compliance"] = {
            **compliance,
            "actual_activity": neutral_activity_metrics(compliance["actual_activity"]),
        }
    return translated


def neutral_calendar_entries(entries: Iterable[Any]) -> list[Any]:
    return [neutral_calendar_entry(entry) for entry in entries]
