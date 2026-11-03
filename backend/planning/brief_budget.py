"""Deterministic character budget of the planning brief.

Trims whole entries (oldest weeks first, then later days), never the JSON text,
and names what it dropped in ``omitted``. ``lessons``, ``season_phase`` and
``weekly_plan`` are never trimmed. No I/O.
"""

from __future__ import annotations

import json
from typing import Any, Final

BRIEF_CHARACTER_LIMIT: Final = 20_000
OMITTED_NOTE: Final = "Entries dropped to keep the brief within its size budget; oldest weeks and latest days first."


def brief_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    )


def _trim_list(target: Any, key: str, *, oldest: bool) -> bool:
    items = target.get(key) if isinstance(target, dict) else None
    if not isinstance(items, list) or not items:
        return False
    items.pop(0 if oldest else -1)
    return True


def _trim_dict(target: Any, key: str) -> bool:
    items = target.get(key) if isinstance(target, dict) else None
    if not isinstance(items, dict) or not items:
        return False
    del items[max(items)]
    return True


def _steps(brief: dict[str, Any]) -> list[tuple[str, Any]]:
    """(omitted label, trim callable) in trimming order."""
    return [
        ("weeks", lambda: _trim_list(brief, "weeks", oldest=True)),
        (
            "planned_distribution.weeks",
            lambda: _trim_list(
                brief.get("planned_distribution"), "weeks", oldest=False
            ),
        ),
        (
            "strength.weeks",
            lambda: _trim_list(brief.get("strength"), "weeks", oldest=False),
        ),
        (
            "planned_sessions",
            lambda: _trim_list(brief, "planned_sessions", oldest=False),
        ),
        ("free_time_minutes", lambda: _trim_dict(brief, "free_time_minutes")),
        ("calendar_busy_minutes", lambda: _trim_dict(brief, "calendar_busy_minutes")),
    ]


def fit_brief(
    brief: dict[str, Any], limit: int = BRIEF_CHARACTER_LIMIT
) -> dict[str, Any]:
    """The brief within ``limit`` characters; dropped entry counts go to ``omitted``."""
    if brief_size(brief) <= limit:
        return brief
    result = json.loads(json.dumps(brief))
    omitted: dict[str, int] = {}
    for label, trim in _steps(result):
        while (
            brief_size({**result, "omitted": {"note": OMITTED_NOTE, "counts": omitted}})
            > limit
            and trim()
        ):
            omitted[label] = omitted.get(label, 0) + 1
    if omitted:
        result["omitted"] = {"note": OMITTED_NOTE, "counts": omitted}
    return result
