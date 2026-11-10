"""Local wall-clock start of a planned unit, where midnight means unknown."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any


def known_start(unit: Mapping[str, Any]) -> datetime | None:
    """Return the local start, or None when it is missing or a synthetic midnight.

    Date moves, undo and imports store ``<date>T00:00:00`` when no time exists, so
    midnight is never a real start. An offset is dropped so aware and naive
    starts compare.
    """
    try:
        start = datetime.fromisoformat(str(unit.get("starts_at_local") or ""))
    except ValueError:
        return None
    start = start.replace(tzinfo=None)
    return None if start.time() == time.min else start
