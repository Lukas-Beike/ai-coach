"""Diagnostic list of canonical sessions that hold two records of one origin.

Bundling assigns at most one record per provider and recording origin to a
session. Sessions merged before that rule may still hold two, which almost
always means two separate real sessions were joined. Merges are never undone
automatically, so they are only listed here for the athlete to review.

The link kind counts of the surviving sessions show how their records were
joined; a session that bundles no other session's record counts as ``single``,
whatever matched kind an earlier removal of its copy left stored.
"""

from __future__ import annotations

from typing import Any

_LIMIT = 50

# Alias sessions resolve one level through ``merged_into``; aliases never chain.
_CONFLICTS = """
    SELECT COALESCE(s.merged_into, s.activity_id) AS session_id,
           r.provider AS provider, r.recorded_by AS recorded_by,
           COUNT(*) AS records, MAX(r.local_date) AS local_date
    FROM activity_records r
    JOIN activity_sessions s ON s.activity_id = r.activity_id
    JOIN activity_sessions t ON t.activity_id = COALESCE(s.merged_into, s.activity_id)
    WHERE r.state = 'active' AND s.state <> 'deleted' AND t.state <> 'deleted'
    GROUP BY session_id, r.provider, r.recorded_by
    HAVING COUNT(*) > 1
"""


# A matched kind (exact, heuristic) only counts while another session's record
# is still bundled.
_LINK_KINDS = """
    SELECT CASE WHEN EXISTS (
               SELECT 1 FROM activity_sessions a
               JOIN activity_records r ON r.activity_id = a.activity_id
               WHERE a.merged_into = s.activity_id AND a.state = 'duplicate'
                 AND r.state = 'active')
           OR s.link_kind NOT IN ('exact', 'heuristic')
           THEN s.link_kind ELSE 'single' END AS link_kind,
           COUNT(*) AS count
    FROM activity_sessions s WHERE s.state = 'active'
    GROUP BY 1 ORDER BY 1
"""


def summarize_session_conflicts(db: Any) -> dict[str, Any]:
    """Return the newest sessions holding several active records of one origin.

    Also returns the link kinds of active sessions.
    """
    total = db.execute(f"SELECT COUNT(*) AS count FROM ({_CONFLICTS})").fetchone()[
        "count"
    ]
    rows = db.execute(
        f"{_CONFLICTS} ORDER BY local_date DESC, session_id, provider, recorded_by "
        "LIMIT ?",
        (_LIMIT,),
    ).fetchall()
    return {
        "total": total,
        "sessions": [
            {
                "session_id": row["session_id"],
                "local_date": row["local_date"],
                "provider": row["provider"],
                "recorded_by": row["recorded_by"],
                "records": row["records"],
            }
            for row in rows
        ],
        "link_kinds": {
            row["link_kind"]: row["count"] for row in db.execute(_LINK_KINDS).fetchall()
        },
    }
