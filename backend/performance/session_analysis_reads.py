"""Compact session analyses for reports and the calendar, read from canonical rows."""

from __future__ import annotations

import json
from typing import Any

from backend.db.activity_analysis_reads import recent_session_analyses
from backend.performance.canonical_session_analysis import ANALYSIS_VERSION

_LIMIT = 100


def _recent(database_manager: Any) -> list[dict[str, Any]]:
    """Newest first; equal instants keep their id order."""
    with database_manager.reader() as db:
        return recent_session_analyses(db, ANALYSIS_VERSION, _LIMIT)


def _decoded(value: Any) -> Any:
    return json.loads(value) if value else None


def calendar_profiles(database_manager: Any) -> dict[str, dict[str, Any]]:
    """Recorded workout profiles keyed by session id."""
    return {
        row["id"]: json.loads(row["profile"])
        for row in _recent(database_manager)
        if row["profile"]
    }


def analysis_summaries(database_manager: Any) -> list[dict[str, Any]]:
    """Return bounded scalar analyses keyed by session id, without sensor arrays."""
    return [
        {
            "session_id": row["id"],
            "observed_at": row["observed_at"],
            "source": row["source"],
            "aerobic": json.loads(row["aerobic"]),
            "power_profile": _decoded(row["power_profile"]),
            "running_profile": _decoded(row["running_profile"]),
            "target_snapshot": _decoded(row["targets"]),
            "interval_quality": _decoded(row["interval_quality"]),
        }
        for row in _recent(database_manager)
        if row["aerobic"]
    ]
