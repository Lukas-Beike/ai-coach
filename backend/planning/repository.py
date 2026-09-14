"""Connection-taking persistence operations for planned units."""

from __future__ import annotations

import json
from datetime import date
from typing import Any


def planned_unit_rows(
    db: Any, limit: int, include_archived: bool, future_only: bool, *, today: date,
) -> list[Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("COALESCE(json_extract(payload, '$.archived'), 0) = 0")
    if future_only:
        clauses.extend([
            "COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0",
            "substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) >= ?",
        ])
        params.append(today.isoformat())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return db.execute(
        "SELECT local_id, payload, sync_state, sync_error, sync_conflict FROM planned_units "
        f"{where} ORDER BY json_extract(payload, '$.date'), "
        "lower(json_extract(payload, '$.name')), local_id LIMIT ?",
        (*params, max(1, min(int(limit) * (2 if include_archived else 1), 1000))),
    ).fetchall()


def planned_unit_payload(row: Any, include_archived: bool) -> dict[str, Any] | None:
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, KeyError):
        return None
    if not isinstance(payload, dict) or (not include_archived and payload.get("archived")):
        return None
    payload["id"] = str(row["local_id"] or payload.get("id") or "")
    payload["local_id"] = payload["id"]
    payload["sync_status"] = str(row["sync_state"] or payload.get("sync_status") or "local")
    if row["sync_error"]:
        payload["sync_error"] = str(row["sync_error"])[:1000]
    if row["sync_conflict"]:
        try:
            payload["sync_conflict"] = json.loads(row["sync_conflict"])
        except (TypeError, ValueError):
            payload["sync_conflict"] = {"raw": str(row["sync_conflict"])[:1000]}
    return payload
