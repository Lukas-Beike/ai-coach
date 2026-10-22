"""Bounded reads of compact Intervals activity analyses, newest first.

Canonical rows come from ``activity_detail_analysis``; the temporary kv rows
cover activities whose analysis has not been copied to the canonical tables
yet. Both return the same columns and are ordered by the observation instant,
so rows in "Z" and "+00:00" notation compare correctly.
"""

from __future__ import annotations

from typing import Any, Final

from backend.canonical.vocabulary import (
    ActivityRecordState,
    ActivitySessionState,
    ProviderId,
)

_INTERVALS: Final = ProviderId.INTERVALS.value

_CANONICAL_SQL: Final = """
    SELECT r.provider_activity_id AS id,
        -- A stored null is kept; only a payload without the key uses the sets.
        CASE WHEN json_type(a.payload, '$.summary_sha256') IS NOT NULL
            THEN json_extract(a.payload, '$.summary_sha256')
            ELSE (
            SELECT d.summary_sha256 FROM activity_detail_sets AS d
            WHERE d.provider = r.provider
              AND d.provider_activity_id = r.provider_activity_id
              AND d.summary_sha256 IS NOT NULL
            ORDER BY d.fetched_at DESC LIMIT 1) END AS fingerprint,
        COALESCE(json_extract(a.payload, '$.observed_at'), (
            SELECT MAX(d.fetched_at) FROM activity_detail_sets AS d
            WHERE d.provider = r.provider
              AND d.provider_activity_id = r.provider_activity_id),
            a.computed_at) AS observed_at,
        json_extract(a.payload, '$.calendar_profile') AS profile,
        json_extract(a.payload, '$.session_analysis.aerobic') AS aerobic,
        json_extract(a.payload, '$.session_analysis.power_profile') AS power_profile,
        json_extract(a.payload, '$.session_analysis.running_profile') AS running_profile,
        json_extract(a.payload, '$.target_snapshot') AS targets,
        json_extract(a.payload, '$.session_analysis.interval_quality') AS interval_quality
    FROM activity_detail_analysis AS a
    JOIN activity_sessions AS s ON s.activity_id = a.activity_id AND s.state <> ?
    JOIN activity_records AS r ON r.activity_id = a.activity_id
        AND r.provider = ? AND r.state = ?
"""

# Temporary fallback: kv records of linked activities without a canonical analysis.
_KV_SQL: Final = """
    SELECT r.provider_activity_id AS id,
        json_extract(k.value, '$.summary_sha256') AS fingerprint,
        json_extract(k.value, '$.observed_at') AS observed_at,
        json_extract(k.value, '$.calendar_profile') AS profile,
        json_extract(k.value, '$.session_analysis.aerobic') AS aerobic,
        json_extract(k.value, '$.session_analysis.power_profile') AS power_profile,
        json_extract(k.value, '$.session_analysis.running_profile') AS running_profile,
        json_extract(k.value, '$.target_snapshot') AS targets,
        json_extract(k.value, '$.session_analysis.interval_quality') AS interval_quality
    FROM kv AS k
    JOIN activity_records AS r ON r.provider = ?
        AND r.provider_activity_id = json_extract(k.value, '$.activity_id')
        AND r.state = ?
    JOIN activity_sessions AS s ON s.activity_id = r.activity_id AND s.state <> ?
    WHERE substr(k.key, 1, 16) = 'activity_detail:'
      AND NOT EXISTS (
        SELECT 1 FROM activity_detail_analysis AS a WHERE a.activity_id = r.activity_id)
"""


def _wrap(inner: str) -> str:
    return (
        f"SELECT *, julianday(observed_at) AS instant FROM ({inner}) "
        "ORDER BY instant DESC, id LIMIT ?"
    )


def recent_intervals_analyses(db: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Newest canonical analyses of active Intervals activities in live sessions."""
    rows = db.execute(
        _wrap(_CANONICAL_SQL),
        (
            ActivitySessionState.DELETED.value,
            _INTERVALS,
            ActivityRecordState.ACTIVE.value,
            limit,
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_kv_analyses(db: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Newest legacy kv analyses that have no canonical analysis row yet."""
    rows = db.execute(
        _wrap(_KV_SQL),
        (
            _INTERVALS,
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            limit,
        ),
    ).fetchall()
    return [dict(row) for row in rows]
