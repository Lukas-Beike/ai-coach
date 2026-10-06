"""Read Garmin's measured acute load without deriving it from activity loads."""

from typing import Any

from backend.performance.activity_validation import bounded_activity_metric

_ACUTE_LOAD_FIELDS = ("acuteTrainingLoad", "dailyTrainingLoadAcute")


def acute_load_value(record: dict[str, Any]) -> float | None:
    """Read measured acute load fields and reject ambiguous device values."""
    values: set[float] = set()
    pending: list[Any] = [record]
    visited = 0
    while pending and visited < 2000:
        item = pending.pop()
        visited += 1
        if isinstance(item, dict):
            for field in _ACUTE_LOAD_FIELDS:
                value = bounded_activity_metric(item.get(field), 0, 100_000)
                if value is not None:
                    values.add(value)
            pending.extend(
                child for child in item.values() if isinstance(child, (dict, list))
            )
        elif isinstance(item, list):
            pending.extend(item[:500])
    return next(iter(values)) if len(values) == 1 else None
