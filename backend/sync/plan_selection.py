"""Prepare and execute explicitly authorized structured plan pushes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.db import DatabaseManager
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.sync.authority import PlanningAuthorityService
from backend.sync.plan_commands import PlanPushCommandService

_CREATED_ENTRIES_ERROR = (
    "Die neu erstellte Planung muss vor der Synchronisierung lokal gespeichert sein."
)
_CHANGED_ENTRIES_ERROR = (
    "Die geänderten Planungseinheiten müssen vor der Synchronisierung feststehen."
)
_CHANGED_SCOPE_ERROR = (
    "Die Synchronisierung muss genau die in diesem Turn geänderten Einheiten umfassen."
)
_ALL_PENDING_SCOPE_ERROR = (
    "Die Synchronisierung muss alle offenen Einheiten der lokalen Bibliothek umfassen."
)
_SELECTED_SCOPE_ERROR = (
    "Die Synchronisierung muss genau die in diesem Turn erstellten Einheiten umfassen."
)
_STALE_PLAN_ERROR = (
    "Die ausgewählte Planung wurde geändert. Lies den aktuellen Stand erneut."
)


@dataclass
class PreparedPlanSync:
    mode: str
    entries: list[dict[str, Any]]
    required_scope_groups: tuple[tuple[str, ...], ...]


class StructuredPlanSyncService:
    """Own read-only plan-sync selection and its authorized mutation/queue step."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        planning_authority_service: PlanningAuthorityService,
        plan_push_command_service: PlanPushCommandService,
        coach_training_change_limit: int,
    ) -> None:
        self._database_manager = database_manager
        self._authority = planning_authority_service
        self._plan_push = plan_push_command_service
        self._coach_training_change_limit = coach_training_change_limit

    def prepare(
        self, entries: list[dict[str, Any]] | None, intent: dict[str, Any]
    ) -> PreparedPlanSync:
        if entries is None:
            if intent.get("_sync_created_entries_only"):
                raise AppError(409, _CREATED_ENTRIES_ERROR, reason="plan_commit_required")
            if not intent.get("_sync_changed_entries_only"):
                return PreparedPlanSync("all", [], (("local_plan",),))

            changed_ids = {
                str(value).strip()
                for value in intent.get("_changed_sync_entry_ids") or []
                if str(value).strip()
            }
            if not changed_ids:
                raise AppError(409, _CHANGED_ENTRIES_ERROR, reason="plan_changes_required")
            pending_by_id = {
                entry["library_workout_id"]: entry
                for entry in self._authority.pending_plan_push_entries()
            }
            if not changed_ids.issubset(pending_by_id):
                raise AppError(403, _CHANGED_SCOPE_ERROR, reason="intent_scope_denied")
            selected = [pending_by_id[local_id] for local_id in sorted(changed_ids)]
            groups = tuple(
                (
                    f"planned_unit:{entry['library_workout_id']}",
                    f"library_workout:{entry['library_workout_id']}",
                )
                for entry in selected
            )
            return PreparedPlanSync("changed", selected, groups)

        authorized_ids = {
            str(value).strip()
            for key in (
                "_replacement_sync_entry_ids",
                "_created_sync_entry_ids",
                "_changed_sync_entry_ids",
            )
            for value in intent.get(key) or []
            if str(value).strip()
        }
        normalized = planning_library.library_bulk_request_entries(
            entries,
            require_hash=True,
            max_entries=(
                self._coach_training_change_limit
                if authorized_ids or intent.get("_sync_all_pending")
                else planning_library.LIBRARY_BULK_MAX_ENTRIES
            ),
        )
        normalized_ids = {entry["library_workout_id"] for entry in normalized}
        if intent.get("_sync_all_pending"):
            pending_ids = {
                entry["library_workout_id"]
                for entry in self._authority.pending_plan_push_entries()
            }
            if normalized_ids != pending_ids:
                raise AppError(403, _ALL_PENDING_SCOPE_ERROR, reason="intent_scope_denied")
            groups = (("local_plan",),)
        else:
            groups = tuple(
                (
                    f"planned_unit:{entry['library_workout_id']}",
                    f"library_workout:{entry['library_workout_id']}",
                )
                for entry in normalized
            )
        if authorized_ids and normalized_ids != authorized_ids:
            raise AppError(403, _SELECTED_SCOPE_ERROR, reason="intent_scope_denied")
        return PreparedPlanSync("selected", normalized, groups)

    def execute(
        self,
        prepared: PreparedPlanSync,
        sync_job_ids: list[str],
        *,
        reason: str,
    ) -> dict[str, Any]:
        if prepared.mode == "all":
            self._authority.mark_planning_authoritative()
            entries = self._authority.pending_plan_push_entries()
        elif prepared.mode == "changed":
            ids = [entry["library_workout_id"] for entry in prepared.entries]
            self._authority.mark_planning_authoritative(ids)
            entries = prepared.entries
        elif prepared.mode == "selected":
            entries = prepared.entries
            ids = [entry["library_workout_id"] for entry in entries]
            with self._database_manager.unit_of_work() as db:
                for entry in entries:
                    row = db.execute(
                        "SELECT payload FROM planned_units WHERE local_id=?",
                        (entry["library_workout_id"],),
                    ).fetchone()
                    if not row or planning_library.library_payload_hash(
                        row["payload"]
                    ) != entry["expected_payload_hash"]:
                        raise AppError(
                            409,
                            _STALE_PLAN_ERROR,
                            reason="planning_revision_conflict",
                        )
                self._authority.mark_planning_authoritative(ids)
                for entry in entries:
                    row = db.execute(
                        "SELECT payload FROM planned_units WHERE local_id=?",
                        (entry["library_workout_id"],),
                    ).fetchone()
                    entry["expected_payload_hash"] = planning_library.library_payload_hash(
                        row["payload"]
                    )
        else:
            raise ValueError(f"Unsupported prepared plan-sync mode: {prepared.mode}")
        return self._plan_push.enqueue(entries, sync_job_ids, reason=reason)
