"""Connection-taking persistence for planned-unit synchronization state."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconcileDependencies:
    redact: Callable[[str], str]
    payload_hash: Callable[[Any], str]
    bump_revision: Callable[[Any], None]
    now: str


def persist_planned_unit_state(
    db: Any,
    local_id: str,
    state: str,
    error: str | None,
    remote_event: dict[str, Any] | None,
    *,
    dependencies: ReconcileDependencies,
) -> bool:
    row = db.execute("SELECT payload FROM planned_units WHERE local_id = ?", (local_id,)).fetchone()
    if not row:
        return False
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    payload["sync_status"] = state
    if isinstance(remote_event, dict):
        if remote_event.get("id") not in (None, ""):
            payload["remote_event_id"] = str(remote_event["id"])
        if remote_event.get("external_id") not in (None, ""):
            external_id = str(remote_event["external_id"])
            payload["remote_event_external_id"] = external_id
            payload["external_id"] = external_id
        if state == "synced":
            for key in ("moving_time", "workout_doc", "icu_training_load", "icu_intensity"):
                if remote_event.get(key) is not None:
                    payload[key] = remote_event[key]
                elif key != "moving_time":
                    payload.pop(key, None)
    synced = state == "synced"
    remote_external_id = str(remote_event.get("external_id") or "").strip() if isinstance(remote_event, dict) else ""
    db.execute(
        "UPDATE planned_units SET payload=?, sync_dirty=?, sync_state=?, sync_error=?, "
        "sync_conflict=?, external_id=COALESCE(?, external_id), baseline_hash=COALESCE(?, baseline_hash), "
        "last_synced_at=COALESCE(?, last_synced_at), updated_at=? WHERE local_id=?",
        (
            json.dumps(payload, ensure_ascii=False),
            0 if state in {"synced", "remote_missing"} else 1,
            state,
            dependencies.redact(str(error))[:1000] if error else None,
            "" if state != "conflict" else None,
            remote_external_id or None,
            dependencies.payload_hash(payload) if synced else None,
            dependencies.now if synced else None,
            dependencies.now,
            local_id,
        ),
    )
    dependencies.bump_revision(db)
    return True
