"""Change-history reads and undo restores for equipment records.

Items, activity assignments and maintenance entries live as JSON records in the
key-value table; each kind is one history entity type with its own restore.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.athlete.equipment import (
    ASSIGNMENT_PREFIX,
    EQUIPMENT_PREFIX,
    MAINTENANCE_PREFIX,
    UPSERT_KV,
    equipment_in_use,
    stored_value,
    validate_restored_equipment,
)
from backend.errors import AppError

# Stored only once set; a restore of an unset value removes the key again.
_ITEM_OPTIONAL_FIELDS = ("lifetime_target_source",)


class _EquipmentRecordHistory:
    """The shared read side: one stored record and its audit projection."""

    entity_type = ""
    prefix = ""

    def __init__(self, utc_now: Callable[[], str]) -> None:
        self._utc_now = utc_now

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored record of one recorded change, for change history."""
        value = stored_value(db, self.prefix + entity_id)
        return value, change_history.audit_projection(self.entity_type, value)

    def _write(self, db: Any, entity_id: str, record: dict[str, Any]) -> None:
        db.execute(
            UPSERT_KV,
            (
                self.prefix + entity_id,
                json.dumps(record, allow_nan=False),
                self._utc_now(),
            ),
        )

    def _delete(self, db: Any, entity_id: str) -> None:
        db.execute("DELETE FROM kv WHERE key=?", (self.prefix + entity_id,))

    def _fields(self) -> tuple[str, ...]:
        return tuple(sorted(change_history.audit_projection_fields(self.entity_type)))


class EquipmentItemHistory(_EquipmentRecordHistory):
    entity_type = "equipment"
    prefix = EQUIPMENT_PREFIX

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Put one item back as recorded, or remove an item the change created."""
        if target is None:
            if equipment_in_use(db, entity_id):
                raise AppError(
                    409, "Die Ausrüstung wird bereits verwendet und bleibt erhalten."
                )
            self._delete(db, entity_id)
            return None
        # The target holds only the changed fields, and a stored None is missing.
        restored: dict[str, Any] = {
            **dict.fromkeys(self._fields()),
            **(current or {}),
            **target,
            "id": entity_id,
        }
        for field in _ITEM_OPTIONAL_FIELDS:
            if restored.get(field) is None:
                restored.pop(field, None)
        validate_restored_equipment(db, restored)
        # A new revision keeps a client that read the undone state from saving over it.
        restored["revision"] = int((current or {}).get("revision") or 0) + 1
        restored["updated_at"] = self._utc_now()
        self._write(db, entity_id, restored)
        return restored


class EquipmentAssignmentHistory(_EquipmentRecordHistory):
    entity_type = "equipment_assignment"
    prefix = ASSIGNMENT_PREFIX

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Put one activity's explicit gear back, including an unassignment."""
        if target is None:
            # Without a row the activity has no explicit assignment at all.
            self._delete(db, entity_id)
            return None
        restored = {
            **dict.fromkeys(self._fields()),
            **(current or {}),
            **target,
            "activity_id": entity_id,
        }
        equipment_id = restored["equipment_id"]
        if equipment_id is not None:
            item = stored_value(db, EQUIPMENT_PREFIX + str(equipment_id))
            if item is None or item.get("parent_id"):
                raise AppError(
                    409, "Die frühere Ausrüstung dieser Aktivität ist nicht mehr da."
                )
        restored["observed_at"] = self._utc_now()
        self._write(db, entity_id, restored)
        return restored


class EquipmentMaintenanceHistory(_EquipmentRecordHistory):
    entity_type = "equipment_maintenance"
    prefix = MAINTENANCE_PREFIX

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Remove a logged maintenance entry, or bring a removed one back."""
        if target is None:
            self._delete(db, entity_id)
            return None
        restored = {
            **dict.fromkeys(self._fields()),
            **(current or {}),
            **target,
            "id": entity_id,
        }
        if stored_value(db, EQUIPMENT_PREFIX + str(restored["equipment_id"])) is None:
            raise AppError(
                409, "Die Ausrüstung dieser Wartung ist nicht mehr vorhanden."
            )
        restored["observed_at"] = self._utc_now()
        self._write(db, entity_id, restored)
        return restored


def equipment_history_records(utc_now: Callable[[], str]) -> dict[str, Any]:
    """The change-history record services of the three equipment entity types."""
    return {
        history.entity_type: history
        for history in (
            EquipmentItemHistory(utc_now),
            EquipmentAssignmentHistory(utc_now),
            EquipmentMaintenanceHistory(utc_now),
        )
    }
