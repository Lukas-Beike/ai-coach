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
        expected_payload: str | None = None,
    ) -> bool:
        row = db.execute(
            "SELECT payload, sync_conflict FROM planned_units WHERE local_id = ?",
            (local_id,),
        ).fetchone()
        current = _load_payload(row) if row else None
        changed = expected_payload is not None and (
            row is None or row["payload"] != expected_payload
        )
        if row is None and not changed:
            return False
        if row is None:
            # The user deleted the unit while its create/update was in flight.
            # Keep a local tombstone so the next explicit sync can remove the
            # remote event instead of orphaning it.
            payload = _load_payload({"payload": expected_payload})
            payload.update(local_deleted=True, archived=True)
        else:
            payload = current or {}
        payload["sync_status"] = state
        remote_external_id = _apply_remote_event(
            payload, state if not changed else "identity", remote_event
        )
        baseline_payload = _load_payload({"payload": expected_payload}) if changed else payload
        if changed and state == "synced":
            _apply_remote_event(baseline_payload, state, remote_event)
        persisted_state = "local" if changed and state == "synced" else state
        if changed:
            payload["sync_status"] = persisted_state
        if row is None:
            db.execute(
                "INSERT INTO planned_units(id, local_id, external_id, payload, sync_dirty, "
                "sync_state, sync_error, sync_conflict, baseline_hash, last_synced_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, '', ?, ?, ?, ?)",
                (
                    local_id,
                    local_id,
                    remote_external_id or None,
                    json.dumps(payload, ensure_ascii=False),
                    persisted_state,
                    self._redactor.redact_text(str(error))[:1000] if error else None,
                    planned_unit_payload_hash(baseline_payload) if state == "synced" else None,
                    now if state == "synced" else None,
                    now,
                    now,
                ),
            )
            self._revision_service.bump(db)
            return True
        db.execute(
            "UPDATE planned_units SET payload=?, sync_dirty=?, sync_state=?, sync_error=?, "
            "sync_conflict=?, external_id=COALESCE(?, external_id), baseline_hash=COALESCE(?, baseline_hash), "
            "last_synced_at=COALESCE(?, last_synced_at), updated_at=? WHERE local_id=?",
            (
                json.dumps(payload, ensure_ascii=False),
                1 if changed else 0 if state in {"synced", "remote_missing"} else 1,
                persisted_state,
                self._redactor.redact_text(str(error))[:1000] if error else None,
                row["sync_conflict"] if changed else None if state == "conflict" else "",
                remote_external_id or None,
                planned_unit_payload_hash(baseline_payload) if state == "synced" else None,
                now if state == "synced" else None,
                now,
                local_id,
            ),
        )
        self._revision_service.bump(db)
        return True
