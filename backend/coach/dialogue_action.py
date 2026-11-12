"""Bind a model-selected Coach action to the user's live request and scopes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.canonical.labels import provider_name
from backend.canonical.vocabulary import ProviderId
from backend.coach.authorization import TRAINING_PLAN_SCOPE_PREFIX, require_coach_scope
from backend.coach.dialogue import validate_request
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
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
    "nutrition_template": ("nutrition_templates", "id"),
    # Stored database foods share the table; only own products are objects.
    "nutrition_product": (
        "(SELECT id FROM nutrition_products WHERE origin = 'own')",
        "id",
    ),
}
LOCAL_BROAD_SCOPES = frozenset(
    {
        "local_profile",
        "local_plan",
        "local_template",
        "local_competitions",
        "local_checkin",
        "activity_feedback",
        "adaptive_replan",
        "intervals_sync",
        "garmin_sync",
        "wahoo_sync",
        "local_nutrition",
        "local_nutrition_product",
        "local_equipment",
        "local_activity_session",
    }
)


def broad_scope_tokens(
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
) -> frozenset[str]:
    """Return scope tokens naming a whole area, including each refresh target."""
    refresh = frozenset(
        f"{target}_refresh" for target in registry.coach_refresh_targets()
    )
    return LOCAL_BROAD_SCOPES | refresh


class CoachDialogueActionService:
    """Own request binding, target/remote gates, and live object authorization."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: Any,
        sync_jobs: Callable[[], SyncJobQueueService],
        plan_scope: CoachDialoguePlanScopeService,
        today: Callable[[], date],
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._sync_jobs = sync_jobs
        self._plan_scope = plan_scope
        self._today = today
        self._registry = registry
        self._broad_scopes = broad_scope_tokens(registry)

    def classify(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        allow_mutations: bool,
    ) -> dict[str, Any]:
        if not allow_mutations:
            raise AppError(
                403,
                "Dieser Coach-Lauf dient ausschließlich der Beratung.",
                reason="intent_scope_denied",
            )
        user_ids = {
            item["id"] for item in context["messages"] if item["role"] == "user"
        }
        # A referenced draft may predate the bounded recent dialogue.
        with self._db_lock, self._database_manager.unit_of_work() as db:
            user_ids.update(
                row["id"]
                for row in db.execute(
                    "SELECT m.id FROM messages m JOIN coach_plan_artifacts a ON a.client_turn_id=m.client_turn_id "
                    "WHERE m.role='user' AND a.status='draft'"
                ).fetchall()
            )
        try:
            request = validate_request(
                arguments.pop("_request", None),
                user_ids,
                context["current_user_message_id"],
                registry=self._registry,
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
        if name in {"delete_nutrition_template", "log_nutrition_template"}:
            scope.add("nutrition_template:" + str(arguments.get("id") or ""))
        retry_job = self._retry_job(name, arguments, target)
        remote_write, refresh = self._retry_metadata(name, arguments, retry_job)
        self._validate_target(
            request, target, scope, remote_write, refresh, name, retry_job
        )
        self._validate_objects(name, arguments, scope)
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

    def _retry_job(
        self, name: str, arguments: dict[str, Any], target: str
    ) -> dict[str, Any] | None:
        """Return the job a retry names; its provider and type decide the scope."""
        if name != "resolve_training_sync_conflict" or not arguments.get("job_id"):
            return None
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
                f"Die Wiederholung benötigt das Ziel {provider_name(retry_job['provider'])} des ursprünglichen Jobs.",
                reason="request_target",
            )
        return retry_job

    @staticmethod
    def _retry_metadata(
        name: str, arguments: dict[str, Any], retry_job: dict[str, Any] | None
    ) -> tuple[bool, bool]:
        retry_push = bool(
            retry_job
            and retry_job["type"] in {"plan_push", "competition_push", "nutrition_sync"}
        )
        remote_write = (
            name
            in {
                "start_intervals_plan_sync",
                "push_strength_to_garmin",
                "sync_competitions",
                "sync_nutrition",
            }
            or (
                name == "apply_adaptive_replan"
                and bool(arguments.get("sync_illness_to_intervals"))
            )
            or retry_push
        )
        refresh = bool(retry_job and not retry_push) or name == "start_provider_refresh"
        return remote_write, refresh

    def _validate_target(
        self,
        request: dict[str, Any],
        target: str,
        scope: set[str],
        remote_write: bool,
        refresh: bool,
        name: str = "",
        retry_job: dict[str, Any] | None = None,
    ) -> None:
        # Each remote write names its own provider and that provider's sync
        # scope; a retry takes both from the job it retries.
        provider = str(ProviderId.INTERVALS)
        if retry_job:
            provider = str(retry_job["provider"])
        elif name == "push_strength_to_garmin":
            provider = str(ProviderId.GARMIN)
        sync_scope = f"{provider}_sync"
        if remote_write and (
            not request["remote_write"] or target != provider or sync_scope not in scope
        ):
            raise AppError(
                403,
                f"Für diesen Schritt fehlt der {provider_name(provider)}-Synchronisierungsauftrag.",
                reason="remote_scope_denied",
            )
        if request["remote_write"] != bool(remote_write) or (
            not remote_write and not refresh and target != "local"
        ):
            raise AppError(
                403,
                "Das Ziel passt nicht zu diesem Auftragsschritt.",
                reason="request_target",
            )
        if refresh and (
            target not in self._registry.coach_refresh_targets()
            or f"{target}_refresh" not in scope
        ):
            raise AppError(
                403,
                "Der Datenabruf benötigt ein eindeutiges Anbieterziel.",
                reason="request_target",
            )

    def _validate_objects(
        self, name: str, arguments: dict[str, Any], scope: set[str]
    ) -> None:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            self._validate_scope_tokens(db, name, scope, self._broad_scopes)
        self._validate_template_action_scope(name, arguments, scope)

    @staticmethod
    def _validate_scope_tokens(
        db: Any, name: str, scope: set[str], broad_scopes: frozenset[str]
    ) -> None:
        for token in scope:
            kind, _, object_id = token.partition(":")
            if kind in OBJECT_SCOPE_TABLES and object_id:
                table, column = OBJECT_SCOPE_TABLES[kind]
                if not db.execute(
                    f"SELECT 1 FROM {table} WHERE {column}=?", (object_id,)
                ).fetchone():
                    raise AppError(
                        409,
                        "Das ausgewählte Objekt ist nicht mehr verfügbar. Lies den aktuellen Stand erneut.",
                        reason="request_object_missing",
                    )
                if CoachDialogueActionService._is_archived_plan(
                    db, name, kind, object_id
                ):
                    raise AppError(
                        409,
                        "Dieser Plan ist archiviert. Wähle den aktuellen Plan oder erstelle einen neuen.",
                        reason="request_object_missing",
                    )
            elif token not in broad_scopes:
                raise AppError(
                    400,
                    "Der Auftrag enthält einen ungültigen Objektbezug.",
                    reason="request_scope",
                )

    @staticmethod
    def _is_archived_plan(db: Any, name: str, kind: str, object_id: str) -> bool:
        if kind != "training_plan" or name != "replace_training_plan":
            return False
        row = db.execute(
            "SELECT status FROM training_plans WHERE id=?", (object_id,)
        ).fetchone()
        return bool(row and row["status"] == "archived")

    @staticmethod
    def _validate_template_action_scope(
        name: str, arguments: dict[str, Any], scope: set[str]
    ) -> None:
        if name not in {"delete_nutrition_template", "log_nutrition_template"}:
            return
        template_id = str(arguments.get("id") or "")
        if f"nutrition_template:{template_id}" not in scope:
            raise AppError(
                403,
                "Die Aktion umfasst diese gespeicherte Mahlzeit nicht.",
                reason="request_scope",
            )

    def _validate_repair_scope(
        self,
        arguments: dict[str, Any],
        request: dict[str, Any],
        action: dict[str, Any],
    ) -> None:
        if not arguments.get("repair"):
            return
        period = request.get("period")
        if request["sync_scope"] != "selected" or not period:
            raise AppError(
                400,
                "Reparatur-Sync benötigt eine Auswahl und einen Zeitraum.",
                reason="request_sync",
            )
        action["_repair_period"] = {
            **period,
            "start": max(period["start"], self._today().isoformat()),
        }
        with self._db_lock, self._database_manager.unit_of_work() as db:
            for entry in arguments.get("entries") or []:
                row = db.execute(
                    SELECT_PLANNED_PAYLOAD_SQL,
                    (str(entry.get("library_workout_id") or ""),),
                ).fetchone()
                day = str(json.loads(row["payload"]).get("date") or "") if row else ""
                if not action["_repair_period"]["start"] <= day <= period["end"]:
                    raise AppError(
                        403,
                        "Die Reparaturauswahl liegt ausserhalb des beauftragten Zeitraums.",
                        reason="request_period",
                    )

    def _apply_operation_scope(
        self,
        name: str,
        arguments: dict[str, Any],
        action: dict[str, Any],
    ) -> None:
        self._apply_planning_scope(name, arguments, action)
        self._apply_sync_scope(name, arguments, action)
        self._apply_object_scope(name, arguments, action)

    def _apply_planning_scope(
        self, name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if name in {
            "apply_training_patch",
            "apply_training_changes",
            "replace_training_plan",
            "stage_training_plan",
            "commit_training_plan",
            "apply_workout_library_plan",
        }:
            period = action["request"]["period"]
            if not period or period["end"] < self._today().isoformat():
                raise AppError(
                    400,
                    "Für die Planung fehlt ein gültiger zukünftiger Zeitraum.",
                    reason="request_period",
                )
            action["period"] = {
                **period,
                "start": max(period["start"], self._today().isoformat()),
            }
            self._plan_scope.validate(name, arguments, action)

    def _apply_sync_scope(
        self, name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if name == "start_intervals_plan_sync":
            if action["request"]["sync_scope"] not in {
                "created",
                "selected",
                "all_pending",
            }:
                raise AppError(
                    400, "Der Umfang der Synchronisierung fehlt.", reason="request_sync"
                )
            action["_sync_all_pending"] = (
                action["request"]["sync_scope"] == "all_pending"
            )
            self._validate_repair_scope(arguments, action["request"], action)
        if name == "push_strength_to_garmin":
            _apply_garmin_scope(arguments, action)
        if name == "sync_nutrition":
            require_coach_scope(action, "local_nutrition", "intervals_sync")

    @staticmethod
    def _apply_object_scope(
        name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        CoachDialogueActionService._apply_training_object_scope(name, arguments, action)
        CoachDialogueActionService._apply_nutrition_object_scope(
            name, arguments, action
        )

    @staticmethod
    def _apply_training_object_scope(
        name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if name == "update_training_plan":
            require_coach_scope(
                action,
                TRAINING_PLAN_SCOPE_PREFIX
                + str((arguments.get("payload") or {}).get("plan_id") or ""),
            )
        if name == "apply_adaptive_replan":
            require_coach_scope(
                action, "adaptive_replan:" + str(arguments.get("adjustment_id") or "")
            )

    @staticmethod
    def _apply_nutrition_object_scope(
        name: str, arguments: dict[str, Any], action: dict[str, Any]
    ) -> None:
        if name in {
            "save_nutrition_template",
            "save_nutrition_product",
            "fill_nutrition_product_gaps",
            "delete_nutrition_template",
            "log_nutrition_template",
            "save_nutrition_entry",
            "update_nutrition_entry",
            "delete_nutrition_entry",
        }:
            template_id = CoachDialogueActionService._nutrition_template_id(
                name, arguments
            )
            if name == "save_nutrition_product":
                product_id = str((arguments.get("payload") or {}).get("id") or "")
                require_coach_scope(
                    action,
                    f"nutrition_product:{product_id}"
                    if product_id
                    else "local_nutrition_product",
                )
            elif name == "fill_nutrition_product_gaps":
                require_coach_scope(action, "local_nutrition_product")
            elif name != "save_nutrition_template" or template_id is None:
                require_coach_scope(action, "local_nutrition")
            if template_id is not None:
                require_coach_scope(action, f"nutrition_template:{template_id}")

    @staticmethod
    def _nutrition_template_id(name: str, arguments: dict[str, Any]) -> str | None:
        """Return the template a tool call targets, or None for no template scope."""
        if name in {"delete_nutrition_template", "log_nutrition_template"}:
            return str(arguments.get("id") or "")
        if name != "save_nutrition_template":
            return None
        payload = arguments.get("payload")
        template_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        return template_id or None


def _apply_garmin_scope(arguments: dict[str, Any], action: dict[str, Any]) -> None:
    """Require a selected sync and every unit in the validated request scope.

    As for an Intervals.icu selection, the model's entries grant nothing alone.
    """
    if action["request"]["sync_scope"] != "selected":
        raise AppError(
            400, "Der Umfang der Synchronisierung fehlt.", reason="request_sync"
        )
    for entry in arguments.get("entries") or []:
        local_id = str(entry.get("local_id") or "") if isinstance(entry, dict) else ""
        if not local_id:
            raise AppError(
                400, "Jede Einheit benötigt ihre local_id.", reason="request_scope"
            )
        require_coach_scope(action, f"planned_unit:{local_id}")
