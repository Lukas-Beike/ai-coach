"""Prepare and execute explicitly authorized structured plan pushes."""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any

from backend.db import DatabaseManager, planning_store
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import planned_units
from backend.planning.intervals_orphans import leftover_ids
from backend.planning.leftovers import MAX_CLEANUP
from backend.planning.push_state import INTERVALS_INDOOR_RIDES_ONLY
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
_ALL_PENDING_MAX_ENTRIES = 5000


@dataclass
class PreparedPlanSync:
    mode: str
    entries: list[dict[str, Any]]
    required_scope_groups: tuple[tuple[str, ...], ...]
    # Units of the turn Intervals.icu takes no part in, dropped before the scope check.
    skipped: int = 0


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
            return self._prepare_implicit_selection(intent)
        dropped = len(intent.get("_skipped_sync_entry_ids") or [])
        if not entries and dropped:
            return PreparedPlanSync("selected", [], (), dropped)
        prepared = self._prepare_explicit_selection(entries, intent)
        prepared.skipped = dropped
        return prepared

    def _prepare_implicit_selection(self, intent: dict[str, Any]) -> PreparedPlanSync:
        if intent.get("_sync_created_entries_only"):
            raise AppError(409, _CREATED_ENTRIES_ERROR, reason="plan_commit_required")
        if not intent.get("_sync_changed_entries_only"):
            return PreparedPlanSync("all", [], (("local_plan",),))
        return self._prepare_changed_selection(intent)

    def _prepare_changed_selection(self, intent: dict[str, Any]) -> PreparedPlanSync:
        changed_ids = {
            str(value).strip()
            for value in intent.get("_changed_sync_entry_ids") or []
            if str(value).strip()
        }
        if not changed_ids:
            raise AppError(409, _CHANGED_ENTRIES_ERROR, reason="plan_changes_required")
        skipped = self._authority.intervals_skipped(changed_ids)
        if skipped and skipped == changed_ids:
            return PreparedPlanSync("changed", [], (), len(skipped))
        changed_ids -= skipped
        pending_by_id = {
            entry["library_workout_id"]: entry
            for entry in self._authority.pending_plan_push_entries()
        }
        if not changed_ids.issubset(pending_by_id):
            raise AppError(403, _CHANGED_SCOPE_ERROR, reason="intent_scope_denied")
        selected = [pending_by_id[local_id] for local_id in sorted(changed_ids)]
        groups = self._scope_groups(selected, intent)
        return PreparedPlanSync("changed", selected, groups, len(skipped))

    def _prepare_explicit_selection(
        self, entries: list[dict[str, Any]], intent: dict[str, Any]
    ) -> PreparedPlanSync:
        authorized_ids = self._authorized_entry_ids(intent)
        normalized = self._normalize_explicit_entries(entries, intent, authorized_ids)
        groups = self._explicit_scope_groups(normalized, intent, authorized_ids)
        return PreparedPlanSync("selected", normalized, groups)

    @staticmethod
    def _authorized_entry_ids(intent: dict[str, Any]) -> set[str]:
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
        return authorized_ids

    def _normalize_explicit_entries(
        self,
        entries: list[dict[str, Any]],
        intent: dict[str, Any],
        authorized_ids: set[str],
    ) -> list[dict[str, Any]]:
        if intent.get("_sync_all_pending"):
            max_entries = _ALL_PENDING_MAX_ENTRIES
        elif authorized_ids:
            # The turn's units plus the leftovers its proposal adds (#2373).
            max_entries = self._coach_training_change_limit + MAX_CLEANUP
        else:
            max_entries = planning_library.LIBRARY_BULK_MAX_ENTRIES
        normalized = planning_library.library_bulk_request_entries(
            entries,
            require_hash=True,
            max_entries=max_entries,
        )
        entity_by_id = {
            str(
                entry.get("library_workout_id") or entry.get("local_id") or ""
            ): entry.get("entity")
            for entry in entries
            if isinstance(entry, dict)
        }
        for entry in normalized:
            entity = entity_by_id.get(entry["library_workout_id"])
            if entity in {"planned_unit", "workout_library"}:
                entry["entity"] = entity
        return normalized

    def _explicit_scope_groups(
        self,
        normalized: list[dict[str, Any]],
        intent: dict[str, Any],
        authorized_ids: set[str],
    ) -> tuple[tuple[str, ...], ...]:
        normalized_ids = {entry["library_workout_id"] for entry in normalized}
        if intent.get("_sync_all_pending"):
            pending_ids = {
                entry["library_workout_id"]
                for entry in self._authority.pending_plan_push_entries()
            }
            if normalized_ids != pending_ids:
                raise AppError(
                    403, _ALL_PENDING_SCOPE_ERROR, reason="intent_scope_denied"
                )
            groups: tuple[tuple[str, ...], ...] = (("local_plan",),)
        else:
            groups = self._scope_groups(normalized, intent)
        # A turn whose units were all skipped still admits only leftovers.
        if (authorized_ids or intent.get("_skipped_sync_entry_ids")) and not (
            self._turn_scope(normalized_ids, authorized_ids)
        ):
            raise AppError(403, _SELECTED_SCOPE_ERROR, reason="intent_scope_denied")
        return groups

    def _turn_scope(self, normalized_ids: set[str], authorized_ids: set[str]) -> bool:
        """Every unit of the turn, plus only leftovers of hidden units (#2373)."""
        extra = normalized_ids - authorized_ids
        if not authorized_ids <= normalized_ids:
            return False
        if not extra:
            return True
        with self._database_manager.reader() as db:
            return leftover_ids(db, extra) == extra

    @staticmethod
    def _scope_groups(
        entries: list[dict[str, Any]], intent: dict[str, Any] | None = None
    ) -> tuple[tuple[str, ...], ...]:
        scopes = {str(value) for value in (intent or {}).get("authorization_scope", [])}
        if not scopes:
            return tuple(
                (
                    f"planned_unit:{entry['library_workout_id']}",
                    f"library_workout:{entry['library_workout_id']}",
                )
                for entry in entries
            )
        return tuple(
            (
                next(
                    (
                        token
                        for token in (
                            f"planned_unit:{entry['library_workout_id']}",
                            f"library_workout:{entry['library_workout_id']}",
                        )
                        if token in scopes
                    ),
                    f"planned_unit:{entry['library_workout_id']}",
                ),
            )
            for entry in entries
        )

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
            entries = prepared.entries
            if entries:
                self._authority.mark_planning_authoritative(
                    [entry["library_workout_id"] for entry in entries]
                )
        elif prepared.mode == "selected":
            entries = self._execute_selected(prepared.entries)
        else:
            raise ValueError(f"Unsupported prepared plan-sync mode: {prepared.mode}")
        return self.report_skips(
            self._plan_push.enqueue(entries, sync_job_ids, reason=reason),
            entries,
            prepared.skipped,
        )

    def report_skips(
        self, result: dict[str, Any], entries: list[dict[str, Any]], dropped: int = 0
    ) -> dict[str, Any]:
        """Name in the receipt how many live units Intervals.icu leaves to other providers."""
        skipped = dropped + len(
            self._authority.intervals_skipped(
                entry["library_workout_id"] for entry in entries
            )
        )
        if not skipped:
            return result
        return {
            **result,
            "skipped": skipped,
            "message": f"{skipped} Einheiten nicht gesendet. {INTERVALS_INDOOR_RIDES_ONLY}.",
        }

    def _execute_selected(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            planned_ids = [
                entry["library_workout_id"]
                for entry in entries
                if self._validate_selected_entry(db, entry) == "planned_unit"
            ]
            if planned_ids:
                self._authority.mark_planning_authoritative(planned_ids)
            for entry in entries:
                row = planning_store.planned_unit_row(db, entry["library_workout_id"])
                if row:
                    entry["expected_payload_hash"] = (
                        planned_units.plan_push_payload_hash(row["payload"])
                    )
        return entries

    @staticmethod
    def _validate_selected_entry(db: Connection, entry: dict[str, Any]) -> str:
        local_id = str(entry["library_workout_id"])
        entity = entry.get("entity")
        rows = []
        if entity != "workout_library":
            rows.append(("planned_unit", planning_store.planned_unit_row(db, local_id)))
        if entity != "planned_unit":
            rows.append(("workout_library", planning_store.library_row(db, local_id)))
        matching = next(
            (
                kind
                for kind, row in rows
                if row
                and planned_units.plan_push_hash_matches(
                    row["payload"], entry["expected_payload_hash"]
                )
            ),
            None,
        )
        if not matching:
            raise AppError(409, _STALE_PLAN_ERROR, reason="planning_revision_conflict")
        return matching
