"""Compact activity analyses for reports and the calendar, read canonically first.

Temporary kv fallback: linked activities whose analysis is not yet in the
canonical tables are served from the legacy detail records until those stop.
"""

from __future__ import annotations

import json
from typing import Any

from backend.db.activity_analysis_reads import (
    recent_intervals_analyses,
    recent_kv_analyses,
)

_LIMIT = 100


def _recent(database_manager: Any) -> list[dict[str, Any]]:
    with database_manager.reader() as db:
        rows = recent_intervals_analyses(db, _LIMIT)
        rows += recent_kv_analyses(db, _LIMIT)
    rows.sort(key=lambda row: row["id"])
    # The reverse sort is stable, so equal instants keep their id order.
    rows.sort(
        key=lambda row: float("-inf") if row["instant"] is None else row["instant"],
        reverse=True,
    )
    return rows[:_LIMIT]


def _decoded(value: Any) -> Any:
    return json.loads(value) if value else None


def calendar_profiles(database_manager: Any) -> dict[str, dict[str, Any]]:
    return {
        row["id"]: {
            "fingerprint": row["fingerprint"],
            "profile": json.loads(row["profile"]),
        }
        for row in _recent(database_manager)
        if row["profile"]
    }


def analysis_summaries(database_manager: Any) -> list[dict[str, Any]]:
    """Return bounded scalar analyses without transferring sensor arrays."""
    return [
        {
            "activity_id": row["id"],
            "summary_sha256": row["fingerprint"],
            "observed_at": row["observed_at"],
            "aerobic": json.loads(row["aerobic"]),
            "power_profile": _decoded(row["power_profile"]),
            "running_profile": _decoded(row["running_profile"]),
            "target_snapshot": _decoded(row["targets"]),
            "interval_quality": _decoded(row["interval_quality"]),
        }
        for row in _recent(database_manager)
        if row["aerobic"]
    ]
