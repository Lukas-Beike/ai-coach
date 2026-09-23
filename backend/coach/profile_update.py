"""Atomic, scoped Coach updates to the athlete's local profile."""

from __future__ import annotations

from typing import Any

from backend.athlete.profile import DEFAULT_PROFILE, ProfileService
from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class CoachProfileUpdateService:
    """Own field validation and optimistic conflict checks before profile save."""

    def __init__(
        self, profile: ProfileService, database_manager: DatabaseManager, database_lock: Any
    ) -> None:
        self._profile = profile
        self._database_manager = database_manager
        self._database_lock = database_lock

    def apply(self, arguments: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        if "update_profile" not in authorized_operations(intent):
            raise AppError(403, "Dieser Auftrag erlaubt keine Profiländerung.", reason="intent_scope_denied")
        require_coach_scope(intent, "local_profile")
        changes = arguments.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= len(DEFAULT_PROFILE):
            raise AppError(400, "Die Profiländerung benötigt gültige Felder.", reason="tool_arguments_invalid")
        with self._database_lock, self._database_manager.unit_of_work():
            current = self._profile.get()
            updated = dict(current)
            seen: set[str] = set()
            for change in changes:
                if (
                    not isinstance(change, dict)
                    or set(change) != {"field", "expected_value", "value"}
                    or not isinstance(change.get("field"), str)
                    or change["field"] not in DEFAULT_PROFILE
                    or change["field"] in seen
                    or any(
                        not isinstance(change.get(key), str) or len(change[key]) > 4000
                        for key in ("expected_value", "value")
                    )
                ):
                    raise AppError(400, "Die Profiländerung enthält ungültige oder doppelte Felder.", reason="tool_arguments_invalid")
                field = change["field"]
                seen.add(field)
                if current[field] != change["expected_value"]:
                    raise AppError(409, "Das Profil wurde inzwischen geändert. Lies es erneut und ergänze den aktuellen Stand.", reason="profile_conflict")
                updated[field] = change["value"]
            saved = self._profile.save(updated)
        return {"ok": True, "stored_locally": True, "updated_fields": sorted(seen), "profile": saved}
