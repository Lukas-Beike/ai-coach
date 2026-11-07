"""Bounded reads of stored canonical session analyses, newest first.

Rows come from canonical ``activity_detail_analysis`` rows (#1685), keyed by the live
session they belong to, and are ordered by the session start instant, so rows
in "Z" and "+00:00" notation compare correctly. Rows of other versions are never read.
"""

from __future__ import annotations

from typing import Any, Final

from backend.canonical.vocabulary import ActivitySessionState

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
