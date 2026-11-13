"""Parse stored planned-unit rows; the SQL lives in ``backend.db.planning_store``."""

from __future__ import annotations

import json
from typing import Any

from backend.planning.sport import with_activity_type


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
