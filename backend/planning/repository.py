"""Connection-taking persistence operations for planned units."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from backend.planning.sport import with_activity_type


def planned_unit_rows(
    db: Any,
    limit: int,
    include_archived: bool,
    future_only: bool,
    *,
    today: date,
) -> list[Any]:
    clauses: list[str] = []
    if not include_archived:
        clauses.append("COALESCE(json_extract(payload, '$.archived'), 0) = 0")
    if future_only:
        clauses.append("COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0")
    day = "substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10)"
    columns = "local_id, payload, sync_state, sync_error, sync_conflict"
    ascending = (
        "json_extract(payload, '$.date'), lower(json_extract(payload, '$.name')), "
        "local_id"
    )
    descending = (
        "json_extract(payload, '$.date') DESC, "
        "lower(json_extract(payload, '$.name')) DESC, local_id DESC"
    )
    bounded_limit = max(1, min(int(limit) * (2 if include_archived else 1), 1000))

    def select(extra: str, order: str, count: int) -> list[Any]:
        where = " AND ".join([*clauses, extra])
        sql = f"SELECT {columns} FROM planned_units WHERE {where} ORDER BY {order} LIMIT ?"
        return db.execute(sql, (today.isoformat(), count)).fetchall()

    upcoming_filter = f"{day} >= ?"
    if future_only:
        return select(upcoming_filter, ascending, bounded_limit)
    # A limited window is anchored on today: the nearest upcoming units plus the
    # most recent past ones. A side that has fewer rows than its half hands the
    # unused share to the other side.
    upcoming = select(upcoming_filter, ascending, bounded_limit)
    past = select(f"{day} < ?", descending, bounded_limit)
    past_share = min(len(past), bounded_limit // 2)
    upcoming_count = min(len(upcoming), bounded_limit - past_share)
    past_count = min(len(past), bounded_limit - upcoming_count)
    return [*reversed(past[:past_count]), *upcoming[:upcoming_count]]


def planned_unit_payload(row: Any, include_archived: bool) -> dict[str, Any] | None:
    try:
        payload = json.loads(row["payload"] or "{}")
    except TypeError, ValueError, KeyError:
        return None
    if not isinstance(payload, dict) or (
        not include_archived and payload.get("archived")
    ):
        return None
    with_activity_type(payload)
    payload["id"] = str(row["local_id"] or payload.get("id") or "")
    payload["local_id"] = payload["id"]
    payload["sync_status"] = str(
        row["sync_state"] or payload.get("sync_status") or "local"
    )
    if row["sync_error"]:
        payload["sync_error"] = str(row["sync_error"])[:1000]
    if row["sync_conflict"]:
        try:
            payload["sync_conflict"] = json.loads(row["sync_conflict"])
        except TypeError, ValueError:
            payload["sync_conflict"] = {"raw": str(row["sync_conflict"])[:1000]}
    return payload
