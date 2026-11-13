"""Merge of identified provider rows."""

from __future__ import annotations

from typing import Any

from backend.activities.matching import first_present as _first_present

__all__ = ["deduplicate_api_records"]


def deduplicate_api_records(records: list[Any]) -> list[Any]:
    """Merge date-window responses without duplicating identified rows."""
    result: list[Any] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            result.append(record)
            continue
        identifier = _first_present(record, ("id", "activityId", "external_id"))
        if identifier in (None, ""):
            result.append(record)
            continue
        key = str(identifier)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result
