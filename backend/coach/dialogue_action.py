"""Bind a model-selected Coach action to the user's live request and scopes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.coach.authorization import TRAINING_PLAN_SCOPE_PREFIX, require_coach_scope
from backend.coach.dialogue import validate_request
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.sync.queue import SyncJobQueueService

SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"

OBJECT_SCOPE_TABLES = {
    "planned_unit": ("planned_units", "local_id"),
    "library_workout": ("workout_library", "local_id"),
    "training_plan": ("training_plans", "id"),
    "competition": ("competitions", "id"),
    "artifact": ("coach_plan_artifacts", "id"),
    "adaptive_replan": ("plan_adjustments", "id"),
    "change": ("change_history", "id"),
    "sync_job": ("sync_jobs", "id"),
}
BROAD_SCOPES = frozenset({
    "local_profile", "local_plan", "local_template", "local_competitions",
    "local_checkin", "activity_feedback", "adaptive_replan", "intervals_sync",
    "intervals_refresh", "garmin_refresh", "calendar_refresh", "weather_refresh",
})


class CoachDialogueActionService:
    """Own request binding, target/remote gates, and live object authorization."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: Any,
        sync_jobs: Callable[[], SyncJobQueueService],
        plan_scope: CoachDialoguePlanScopeService,
        today: Callable[[], date],
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._sync_jobs = sync_jobs
        self._plan_scope = plan_scope
        self._today = today

    def classify(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        allow_mutations: bool,
    ) -> dict[str, Any]:
        if not allow_mutations:
            raise AppError(403, "Dieser Coach-Lauf dient ausschließlich der Beratung.", reason="intent_scope_denied")
        user_ids = {item["id"] for item in context["messages"] if item["role"] == "user"}
        # A referenced draft may predate the bounded recent dialogue.
        with self._db_lock, self._database_manager.unit_of_work() as db:
            user_ids.update(row["id"] for row in db.execute(
                "SELECT m.id FROM messages m JOIN coach_plan_artifacts a ON a.client_turn_id=m.client_turn_id "
                "WHERE m.role='user' AND a.status='draft'"
            ).fetchall())
        try:
            request = validate_request(
                arguments.pop("_request", None), user_ids, context["current_user_message_id"]
            )
        except (TypeError, ValueError) as exc:
            error = AppError(
                400,
                "Der Schritt benötigt einen gültigen Bezug zum aktuellen Auftrag. Prüfe die Werkzeugargumente erneut.",
                reason="request_invalid",
            )
            error.validation_reason = str(exc)
            raise error from exc
        target = request["target"]
        scope = set(request["scope"])
        remote_write, refresh = self._retry_metadata(name, arguments, target)
        self._validate_target(request, target, scope, remote_write, refresh)
        self._validate_objects(name, scope)
        action = {
            "intent": "remote_sync" if remote_write or refresh else "local_action",
            "operation": name,
            "target_system": target,
            "authorization_scope": sorted(scope),
            "follow_up_operations": [],
            "artifact_id": arguments.get("artifact_id"),
            "request": request,
            "bulk_change": True,
        }
        self._apply_operation_scope(name, arguments, action)
        return action

    def _retry_metadata(
        self, name: str, arguments: dict[str, Any], target: str
    ) -> tuple[bool, bool]:
        retry_job = None
        if name == "resolve_training_sync_conflict" and arguments.get("job_id"):
            if arguments.get("local_id"):
                raise AppError(
                    400,
                    "Wähle entweder einen lokalen Konflikt oder einen Synchronisationsjob.",
                    reason="tool_arguments_invalid",
                )
            retry_job = self._sync_jobs().state(str(arguments["job_id"]))
            if target != retry_job["provider"]:
                raise AppError(
                    403,
                    "Die Wiederholung benötigt den Anbieter des ursprünglichen Jobs.",
                    reason="request_target",
                )
        retry_push = bool(retry_job and retry_job["type"] in {"plan_push", "competition_push"})
        remote_write = retry_push or name in {"start_intervals_plan_sync", "sync_competitions"} or (
            name == "apply_adaptive_replan" and arguments.get("sync_illness_to_intervals")
        )
        refresh = bool(retry_job and not retry_push) or name in {
            "start_provider_refresh", "refresh_current_performance",
        }
        return remote_write, refresh

    @staticmethod
    def _validate_target(
        request: dict[str, Any], target: str, scope: set[str], remote_write: bool, refresh: bool
    ) -> None:
        if remote_write and (not request["remote_write"] or target != "intervals" or "intervals_sync" not in scope):
            raise AppError(
                403, "Für diesen Schritt fehlt der zugehörige Synchronisierungsauftrag.",
                reason="remote_scope_denied",
            )
        if request["remote_write"] != bool(remote_write) or (not remote_write and not refresh and target != "local"):
            raise AppError(403, "Das Ziel passt nicht zu diesem Auftragsschritt.", reason="request_target")
        if refresh and (target not in {"intervals", "garmin", "calendar", "weather"} or f"{target}_refresh" not in scope):
            raise AppError(403, "Der Datenabruf benötigt ein eindeutiges Anbieterziel.", reason="request_target")

    def _validate_objects(self, name: str, scope: set[str]) -> None:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            for token in scope:
                kind, _, object_id = token.partition(":")
                if kind in OBJECT_SCOPE_TABLES and object_id:
                    table, column = OBJECT_SCOPE_TABLES[kind]
                    if not db.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (object_id,)).fetchone():
                        raise AppError(
                            409,
                            "Das ausgewählte Objekt ist nicht mehr verfügbar. Lies den aktuellen Stand erneut.",
                            reason="request_object_missing",
                        )
                    if kind == "training_plan" and name == "replace_training_plan" and db.execute(
                        "SELECT status FROM training_plans WHERE id=?", (object_id,)
                    ).fetchone()["status"] == "archived":
                        raise AppError(
                            409,
                            "Dieser Plan ist archiviert. Wähle den aktuellen Plan oder erstelle einen neuen.",
                            reason="request_object_missing",
                        )
                elif token not in BROAD_SCOPES:
                    raise AppError(400, "Der Auftrag enthält einen ungültigen Objektbezug.", reason="request_scope")

    def _validate_repair_scope(
        self, arguments: dict[str, Any], request: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if not arguments.get("repair"):
            return
        period = request.get("period")
        if request["sync_scope"] != "selected" or not period:
            raise AppError(400, "Reparatur-Sync benoetigt eine Auswahl und einen Zeitraum.", reason="request_sync")
        action["_repair_period"] = {**period, "start": max(period["start"], self._today().isoformat())}
        with self._db_lock, self._database_manager.unit_of_work() as db:
            for entry in arguments.get("entries") or []:
                row = db.execute(
                    SELECT_PLANNED_PAYLOAD_SQL, (str(entry.get("library_workout_id") or ""),)
                ).fetchone()
                day = str(json.loads(row["payload"]).get("date") or "") if row else ""
                if not action["_repair_period"]["start"] <= day <= period["end"]:
                    raise AppError(
                        403,
                        "Die Reparaturauswahl liegt ausserhalb des beauftragten Zeitraums.",
                        reason="request_period",
                    )

    def _apply_operation_scope(
        self, name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if name in {
            "apply_training_patch", "apply_training_changes", "replace_training_plan",
            "stage_training_plan", "commit_training_plan", "apply_workout_library_plan",
        }:
            period = action["request"]["period"]
            if not period or period["end"] < self._today().isoformat():
                raise AppError(400, "Für die Planung fehlt ein gültiger zukünftiger Zeitraum.", reason="request_period")
            action["period"] = {**period, "start": max(period["start"], self._today().isoformat())}
            self._plan_scope.validate(name, arguments, action)
        if name == "start_intervals_plan_sync":
            if action["request"]["sync_scope"] not in {"created", "selected", "all_pending"}:
                raise AppError(400, "Der Umfang der Synchronisierung fehlt.", reason="request_sync")
            action["_sync_all_pending"] = action["request"]["sync_scope"] == "all_pending"
            self._validate_repair_scope(arguments, action["request"], action)
        if name == "update_training_plan":
            require_coach_scope(
                action,
                TRAINING_PLAN_SCOPE_PREFIX + str((arguments.get("payload") or {}).get("plan_id") or ""),
            )
        if name == "apply_adaptive_replan":
            require_coach_scope(action, "adaptive_replan:" + str(arguments.get("adjustment_id") or ""))
