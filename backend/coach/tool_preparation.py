"""Prepare structured Coach tool arguments and action scopes for execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.outcomes import unresolved_coach_steps
from backend.errors import AppError
from backend.sync.authority import PlanningAuthorityService
from backend.sync.state import SyncStateRepository


class CoachStructuredToolPreparationService:
    """Bind structured tool actions to authorization and current local state."""

    def __init__(
        self,
        dialogue_action: CoachDialogueActionService,
        sync_state: SyncStateRepository,
        planning_authority: PlanningAuthorityService,
        read_only_tools: frozenset[str],
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
    ) -> None:
        self._dialogue_action = dialogue_action
        self._sync_state = sync_state
        self._planning_authority = planning_authority
        self._read_only_tools = read_only_tools
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days

    def prepare(
        self,
        metadata: dict[str, Any],
        command_receipts: list[dict[str, Any]],
        *,
        question: str,
        cancelled: bool,
        context: dict[str, Any],
        allow_mutations: bool,
    ) -> dict[str, Any]:
        name = metadata["name"]
        arguments = metadata["arguments"]
        action = metadata["action"]
        if (question or cancelled) and name not in self._read_only_tools:
            raise AppError(409, "Der Auftrag wartet auf deine Antwort oder wurde abgebrochen.", reason="request_paused")
        if name not in self._read_only_tools and name not in {"clarify_coach_request", "cancel_coach_request"}:
            action = self._dialogue_action.classify(
                name, arguments, context, allow_mutations=allow_mutations
            )
        if (action.get("request") or {}).get("remote_write") and any(
            entry["tool"] != name and entry["tool"] not in self._read_only_tools
            for entry in unresolved_coach_steps(command_receipts)
        ):
            raise AppError(409, "Vor der Synchronisierung muss der fehlgeschlagene lokale Schritt abgeschlossen werden.", reason="request_dependency")
        if name == "start_provider_refresh" and action.get("target_system") == "intervals":
            arguments["_wait_for_completion"] = True
            arguments.setdefault(
                "days",
                self._sync_state.sync_period(
                    "intervals", self._sync_period_defaults, self._all_sync_days
                ),
            )
        if name == "get_sync_job":
            action["authorization_scope"] = ["sync_job:" + str(arguments.get("job_id") or "")]
        if name == "start_intervals_plan_sync":
            self._prepare_plan_sync(arguments, action, command_receipts)
        return action

    def _prepare_plan_sync(
        self,
        arguments: dict[str, Any],
        action: dict[str, Any],
        command_receipts: list[dict[str, Any]],
    ) -> None:
        sync_scope = action["request"]["sync_scope"]
        if sync_scope == "all_pending":
            arguments.pop("entries", None)
            return
        if sync_scope == "created":
            created_ids = {
                value for entry in command_receipts if entry.get("result", {}).get("ok")
                for value in entry["result"].get("library_entry_ids", [])
            }
            if not created_ids:
                raise AppError(409, "Die neue Planung wurde noch nicht erfolgreich gespeichert.", reason="plan_commit_required")
            entries = [
                entry for entry in self._planning_authority.pending_plan_push_entries()
                if entry["library_workout_id"] in created_ids
            ]
            if {entry["library_workout_id"] for entry in entries} != created_ids:
                raise AppError(409, "Die neue Planung hat sich geändert. Lies den aktuellen Stand erneut.", reason="planning_revision_conflict")
            arguments["entries"] = entries
            action["_created_sync_entry_ids"] = sorted(created_ids)
            action["authorization_scope"].extend(
                "library_workout:" + value for value in created_ids
            )
            return
        if not arguments.get("entries") and not arguments.get("repair"):
            raise AppError(400, "Wähle die zu synchronisierenden Einheiten aus.", reason="request_sync")
