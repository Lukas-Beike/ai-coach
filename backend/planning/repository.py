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
    params: list[Any] = []
    if not include_archived:
        clauses.append("COALESCE(json_extract(payload, '$.archived'), 0) = 0")
    if future_only:
        clauses.extend(
            [
                "COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0",
                "substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) >= ?",
            ]
        )
        params.append(today.isoformat())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    columns = "local_id, payload, sync_state, sync_error, sync_conflict"
    ascending = "json_extract(payload, '$.date'), lower(json_extract(payload, '$.name')), local_id"
    bounded_limit = max(1, min(int(limit) * (2 if include_archived else 1), 1000))
    if future_only:
        sql = f"SELECT {columns} FROM planned_units{where} ORDER BY {ascending} LIMIT ?"
    else:
        # Keep the newest window when limited, then return it in ascending order.
        sql = (
            f"SELECT {columns} FROM (SELECT {columns} FROM planned_units{where} "
            "ORDER BY json_extract(payload, '$.date') DESC, "
            "lower(json_extract(payload, '$.name')) DESC, local_id DESC LIMIT ?) "
            f"ORDER BY {ascending}"
        )
    return db.execute(sql, (*params, bounded_limit)).fetchall()


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
