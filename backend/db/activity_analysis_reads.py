"""Bounded reads of stored canonical session analyses, newest first.

Rows come from canonical ``activity_detail_analysis`` rows (#1685), keyed by the live
session they belong to, and are ordered by the session start instant, so rows
in "Z" and "+00:00" notation compare correctly. Rows of other versions are never read.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Final

from backend.canonical.vocabulary import ActivitySessionState

_CHUNK: Final = 500
_SQL: Final = """
    SELECT a.activity_id AS id,
        json_extract(a.payload, '$.observed_at') AS observed_at,
        json_extract(a.payload, '$.source') AS source,
        json_extract(a.payload, '$.calendar_profile') AS profile,
        json_extract(a.payload, '$.session_analysis.aerobic') AS aerobic,
        json_extract(a.payload, '$.session_analysis.power_profile') AS power_profile,
        json_extract(a.payload, '$.session_analysis.running_profile') AS running_profile,
        json_extract(a.payload, '$.target_snapshot') AS targets,
        json_extract(a.payload, '$.session_analysis.interval_quality') AS interval_quality,
        julianday(s.started_at) AS instant
    FROM activity_detail_analysis AS a
    JOIN activity_sessions AS s ON s.activity_id = a.activity_id
        AND s.state NOT IN (?, ?)
    WHERE a.analysis_version = ?
        AND json_type(a.payload, '$.session_analysis') = 'object'
    ORDER BY instant DESC, id LIMIT ?
"""


def stored_zone_times(
    db: Any, analysis_version: int, session_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """The stored report zone times of ``analysis_version`` rows, by session id."""
    ids = list(dict.fromkeys(session_ids))
    result: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        rows = db.execute(
            "SELECT activity_id, json_extract(payload, '$.zone_times') AS zones "
            "FROM activity_detail_analysis WHERE analysis_version = ? "
            "AND json_type(payload, '$.zone_times') = 'object' "
            f"AND activity_id IN ({', '.join('?' * len(chunk))})",
            (analysis_version, *chunk),
        ).fetchall()
        for row in rows:
            zones = json.loads(row["zones"])
            if isinstance(zones, dict):
                result[row["activity_id"]] = zones
    return result


def recent_session_analyses(
    db: Any, analysis_version: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Newest stored canonical analyses of ``analysis_version`` of live sessions."""
    rows = db.execute(
        _SQL,
        (
            ActivitySessionState.DELETED.value,
            ActivitySessionState.DUPLICATE.value,
            analysis_version,
            limit,
        ),
    ).fetchall()
    return [dict(row) for row in rows]
