"""Read Garmin's measured acute load without deriving it from activity loads."""

from typing import Any

from backend.performance.activity_validation import bounded_activity_metric


def acute_load_value(record: dict[str, Any]) -> float | None:
    """Reject ambiguous device values and unrelated daily/chronic load fields."""
    values: set[float] = set()
    pending: list[Any] = [record]
    visited = 0
    while pending and visited < 2000:
        item = pending.pop()
        visited += 1
        if isinstance(item, dict):
            value = bounded_activity_metric(item.get("acuteTrainingLoad"), 0, 100_000)
            if value is not None:
                values.add(value)
            pending.extend(
                child for child in item.values() if isinstance(child, (dict, list))
            )
        elif isinstance(item, list):
            pending.extend(item[:500])
    return next(iter(values)) if len(values) == 1 else None
