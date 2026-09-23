"""Connection-taking persistence for planned-unit synchronization state."""

from __future__ import annotations

import json
from typing import Any

from backend.observability import Redactor
from backend.planning.planned_units import planned_unit_payload_hash
from backend.planning.revision import PlanningRevisionService


def _load_payload(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _apply_remote_event(
    payload: dict[str, Any], state: str, remote_event: dict[str, Any] | None
) -> str:
    if not isinstance(remote_event, dict):
        return ""
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
    return str(remote_event.get("external_id") or "").strip()


class PlannedUnitSyncStateWriter:
    """Persist planned-unit sync state on a caller-owned connection."""

    def __init__(self, revision_service: PlanningRevisionService, redactor: Redactor):
        self._revision_service = revision_service
        self._redactor = redactor

    def persist(
        self,
        db: Any,
        local_id: str,
        state: str,
        error: str | None,
        remote_event: dict[str, Any] | None,
        *,
        now: str,
    ) -> bool:
        row = db.execute(
            "SELECT payload FROM planned_units WHERE local_id = ?", (local_id,)
        ).fetchone()
        if not row:
            return False
        payload = _load_payload(row)
        payload["sync_status"] = state
        synced = state == "synced"
        remote_external_id = _apply_remote_event(payload, state, remote_event)
        db.execute(
            "UPDATE planned_units SET payload=?, sync_dirty=?, sync_state=?, sync_error=?, "
            "sync_conflict=?, external_id=COALESCE(?, external_id), baseline_hash=COALESCE(?, baseline_hash), "
            "last_synced_at=COALESCE(?, last_synced_at), updated_at=? WHERE local_id=?",
            (
                json.dumps(payload, ensure_ascii=False),
                0 if state in {"synced", "remote_missing"} else 1,
                state,
                self._redactor.redact_text(str(error))[:1000] if error else None,
                "" if state != "conflict" else None,
                remote_external_id or None,
                planned_unit_payload_hash(payload) if synced else None,
                now if synced else None,
                now,
                local_id,
            ),
        )
        self._revision_service.bump(db)
        return True
