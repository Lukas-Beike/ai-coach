"""Preview and atomically apply local change-history undo operations."""

from __future__ import annotations

import re
from typing import Any

from backend import change_history
from backend.errors import AppError

_INVALID_HISTORY_ID = "Ungültige Änderungshistorie-ID."
_MISSING_HISTORY = "Änderung nicht gefunden."
_ALREADY_UNDONE = "Eine Undo-Aktion kann nicht erneut zurückgenommen werden."
_STALE_HISTORY = (
    "Die lokale Änderung wurde inzwischen weiter geändert; Undo wurde abgebrochen."
)


class HistoryUndoService:
    """Own local history validation and its transactional domain restores."""

    def __init__(
        self,
        database_manager: Any,
        history_service: Any,
        profile_service: Any,
        workout_library_service: Any,
        competition_service: Any,
        planned_unit_service: Any,
        training_plan_service: Any,
        planning_revision_service: Any,
    ):
        self._database_manager = database_manager
        self._history_service = history_service
        self._profile_service = profile_service
        self._workout_library_service = workout_library_service
        self._competition_service = competition_service
        self._planned_unit_service = planned_unit_service
        self._training_plan_service = training_plan_service
        self._planning_revision_service = planning_revision_service

    def preview(self, change_id: Any) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            normalized_id, history = self._load_history(db, change_id)
            _, current_projection = self._history_service.current(
                db, history["entity_type"], history["entity_id"]
            )
            current_hash = change_history.audit_hash(current_projection)
            self._require_current_hash(current_hash, history["after_hash"])
            _, target_projection = self._history_service.target(history)
            public_change = change_history.public_view(history)

        return {
            "status": "preview",
            "change": public_change,
            "undo_target_hash": change_history.audit_hash(target_projection),
            "proposal": {
                "action_type": "undo_change",
                "target_system": "local",
                "object_ids": {"change_id": normalized_id},
                "diff": public_change["diff"],
                "payload": {
                    "change_id": normalized_id,
                    "expected_current_hash": current_hash,
                },
            },
        }

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        change_id = payload.get("change_id") if isinstance(payload, dict) else None
        expected_hash = (
            str(payload.get("expected_current_hash") or "")
            if isinstance(payload, dict)
            else ""
        )
        with self._database_manager.unit_of_work() as db:
            _, history = self._load_history(db, change_id)
            entity_type = history["entity_type"]
            entity_id = history["entity_id"]
            current, current_projection = self._history_service.current(
                db, entity_type, entity_id
            )
            current_hash = change_history.audit_hash(current_projection)
            self._require_current_hash(
                current_hash, history["after_hash"], expected_hash
            )
            target, _ = self._history_service.target(history)
            after = self._restore(
                db, entity_type, entity_id, current, target, history["action"]
            )
            if entity_type in {"planned_unit", "training_plan"}:
                self._planning_revision_service.bump(db)
            change_history.record_change(
                db,
                entity_type,
                entity_id,
                "undo",
                current,
                after,
                source="undo",
            )
            result = {
                "status": "undone",
                "change_id": history["id"],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "remote_untouched": True,
            }

        return result

    @staticmethod
    def _load_history(db: Any, change_id: Any) -> tuple[str, dict[str, Any]]:
        normalized_id = str(change_id).strip()
        if re.fullmatch(r"[0-9a-f-]{36}", normalized_id) is None:
            raise AppError(400, _INVALID_HISTORY_ID)
        row = db.execute(
            "SELECT * FROM change_history WHERE id=?", (normalized_id,)
        ).fetchone()
        if row is None:
            raise AppError(404, _MISSING_HISTORY)
        history = dict(row)
        if history["action"] not in {"create", "update", "delete"}:
            raise AppError(409, _ALREADY_UNDONE)
        return normalized_id, history

    @staticmethod
    def _require_current_hash(
        current_hash: str, after_hash: str, expected_hash: str | None = None
    ) -> None:
        if current_hash != after_hash or (
            expected_hash is not None
            and (expected_hash != after_hash or current_hash != expected_hash)
        ):
            raise AppError(409, _STALE_HISTORY)

    def _restore(
        self,
        db: Any,
        entity_type: str,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
        action: str,
    ) -> Any:
        if entity_type == "profile":
            return self._profile_service.restore_in_transaction(db, current, target)
        if entity_type == "workout_library":
            return self._workout_library_service.restore_in_transaction(
                db, entity_id, current, target
            )
        if entity_type == "competition":
            return self._competition_service.restore_in_transaction(
                db, entity_id, current, target
            )
        if entity_type == "planned_unit":
            return self._planned_unit_service.restore_in_transaction(
                db, entity_id, current, target, action
            )
        if entity_type == "training_plan":
            return self._training_plan_service.restore_in_transaction(
                db, entity_id, current, target
            )
        raise AppError(400, "Unbekannte lokale Änderung.")
