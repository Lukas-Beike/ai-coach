"""Diagnostic list of canonical sessions that hold two records of one origin.

Bundling assigns at most one record per provider and recording origin to a
session. Sessions merged before that rule may still hold two, which almost
always means two separate real sessions were joined. Merges are never undone
automatically, so they are only listed here for the athlete to review.

The same holds for exact links that are not applied: an Intervals.icu copy names
its stored upstream record, but the two stay in different sessions, usually
because an earlier heuristic merge joined the copy to another record. Pairs the
athlete confirmed, hid or deleted are kept apart on purpose and not listed. The link
kind counts of the surviving sessions show how their records were joined.
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


# Both ends resolve one level through ``merged_into``, as above.
_EXACT_MISMATCHES = """
    SELECT COALESCE(s.merged_into, s.activity_id) AS session_id,
           COALESCE(us.merged_into, us.activity_id) AS upstream_session_id,
           u.provider AS upstream, r.local_date AS local_date
    FROM (SELECT *, CASE WHEN json_valid(details) THEN details END AS ref
          FROM activity_records
          WHERE provider = 'intervals' AND state = 'active') r
    JOIN activity_sessions s ON s.activity_id = r.activity_id
    JOIN activity_records u
      ON u.provider = json_extract(r.ref, '$.external_ref[0]')
     AND u.provider_activity_id = json_extract(r.ref, '$.external_ref[1]')
    JOIN activity_sessions us ON us.activity_id = u.activity_id
    JOIN activity_sessions t ON t.activity_id = COALESCE(s.merged_into, s.activity_id)
    JOIN activity_sessions ut
      ON ut.activity_id = COALESCE(us.merged_into, us.activity_id)
    WHERE u.state = 'active' AND s.state <> 'deleted' AND us.state <> 'deleted'
      AND t.state = 'active' AND ut.state = 'active'
      AND t.athlete_confirmed = 0 AND ut.athlete_confirmed = 0
      AND t.activity_id <> ut.activity_id
"""
_LINK_KINDS = """
    SELECT link_kind, COUNT(*) AS count FROM activity_sessions
    WHERE state = 'active' GROUP BY link_kind ORDER BY link_kind
"""


def summarize_session_conflicts(db: Any) -> dict[str, Any]:
    """Return the newest sessions holding several active records of one origin.

    Also returns the unapplied exact links and the link kinds of active sessions.
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
        "exact_link_mismatches": _exact_mismatches(db),
        "link_kinds": {
            row["link_kind"]: row["count"] for row in db.execute(_LINK_KINDS).fetchall()
        },
    }


def _exact_mismatches(db: Any) -> dict[str, Any]:
    total = db.execute(
        f"SELECT COUNT(*) AS count FROM ({_EXACT_MISMATCHES})"
    ).fetchone()["count"]
    rows = db.execute(
        f"{_EXACT_MISMATCHES} ORDER BY local_date DESC, session_id, "
        "upstream_session_id LIMIT ?",
        (_LIMIT,),
    ).fetchall()
    return {
        "total": total,
        "sessions": [
            {
                "session_id": row["session_id"],
                "upstream_session_id": row["upstream_session_id"],
                "upstream": row["upstream"],
                "local_date": row["local_date"],
            }
            for row in rows
        ],
    }
