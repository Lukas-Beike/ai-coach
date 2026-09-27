"""Authorize and execute the Coach's explicit synchronization tools."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.activities.duplicates import latest_wahoo_garmin_duplicate
from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.queue import SyncJobQueueService

COACH_SYNC_TOOL_NAMES = frozenset({
    "start_intervals_plan_sync", "get_sync_job", "sync_competitions",
    "sync_nutrition",
    "resolve_training_sync_conflict", "start_provider_refresh", "refresh_current_performance",
    "delete_duplicate_intervals_activity",
})


class CoachSyncToolService:
    """Own authorization and effects for the Coach sync commands."""

    def __init__(
        self,
        queue: SyncJobQueueService,
        authority: PlanningAuthorityService,
        conflicts: SyncConflictCommandService,
        plan_sync: StructuredPlanSyncService,
        plan_repair: PlanRepairManifestService,
        plan_push: PlanPushCommandService,
        provider_refresh: ProviderRefreshCommandService,
        duplicate_activity: Any | None = None,
        intervals_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._queue = queue
        self._authority = authority
        self._conflicts = conflicts
        self._plan_sync = plan_sync
        self._plan_repair = plan_repair
        self._plan_push = plan_push
        self._provider_refresh = provider_refresh
        self._duplicate_activity = duplicate_activity
        self._intervals_client_factory = intervals_client_factory

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        intent: dict[str, Any],
        sync_job_ids: list[str],
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any] | None:
        if name == "start_intervals_plan_sync":
            return self._start_plan_sync(arguments, intent, sync_job_ids)
        if name == "get_sync_job":
            job_id = str(arguments.get("job_id") or "").strip()
            if job_id not in sync_job_ids:
                require_coach_scope(intent, f"sync_job:{job_id}")
            return {"ok": True, "job": self._queue.state(job_id)}
        if name == "sync_competitions":
            return self._sync_competitions(arguments, intent, sync_job_ids)
        if name == "sync_nutrition":
            return self._sync_nutrition(arguments, intent, sync_job_ids)
        if name == "resolve_training_sync_conflict":
            return self._resolve_conflict(arguments, intent, sync_job_ids)
        if name == "start_provider_refresh":
            return self._start_provider_refresh(arguments, intent, sync_job_ids, cancel_event)
        if name == "refresh_current_performance":
            return self._refresh_current_performance(arguments, intent, sync_job_ids)
        if name == "delete_duplicate_intervals_activity":
            return self._delete_duplicate_activity(arguments, intent)
        return None

    def _sync_nutrition(
        self, arguments: dict[str, Any], intent: dict[str, Any], sync_job_ids: list[str]
    ) -> dict[str, Any]:
        if (
            "sync_nutrition" not in authorized_operations(intent)
            or intent.get("target_system") != "intervals"
        ):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")
        require_coach_scope(intent, "local_nutrition", "intervals_sync")
        date_value = str(arguments.get("date") or "").strip()
        limit = arguments.get("pending_limit")
        if bool(date_value) == (limit is not None):
            raise AppError(
                400,
                "Wähle ein Datum oder eine Anzahl ausstehender Tage.",
                reason="invalid_job_request",
            )
        payload = {"date": date_value} if date_value else {"pending_limit": limit}
        job = self._queue.enqueue(
            "intervals", "nutrition_sync", payload, requested_by="coach"
        )
        sync_job_ids.append(job["id"])
        return {"ok": True, "status": "queued", "sync_job_id": job["id"]}

    def _start_provider_refresh(
        self, arguments: dict[str, Any], intent: dict[str, Any],
        sync_job_ids: list[str], cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        if "start_provider_refresh" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")
        provider = str(intent.get("target_system") or "")
        require_coach_scope(intent, f"{provider}_refresh")
        result = self._provider_refresh.start(provider, arguments, cancel_event=cancel_event)
        if result.get("status") == "queued":
            sync_job_ids.append(result["sync_job_id"])
        return result

    def _refresh_current_performance(
        self, arguments: dict[str, Any], intent: dict[str, Any], sync_job_ids: list[str],
    ) -> dict[str, Any]:
        if "refresh_current_performance" not in authorized_operations(intent) or intent.get("target_system") != "intervals":
            raise AppError(403, "Die strukturierte Coach-Autorisierung erlaubt diesen Refresh nicht.", reason="intent_scope_denied")
        require_coach_scope(intent, "intervals_refresh")
        result = self._provider_refresh.queue_performance_refresh(arguments)
        sync_job_ids.append(result["sync_job_id"])
        return result

    def _start_plan_sync(
        self, arguments: dict[str, Any], intent: dict[str, Any], sync_job_ids: list[str]
    ) -> dict[str, Any]:
        if "start_intervals_plan_sync" not in authorized_operations(intent) or intent.get("target_system") != "intervals":
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")
        entries = arguments.get("entries")
        if "repair" in arguments and type(arguments["repair"]) is not bool:
            raise AppError(400, "repair muss ein Boolean sein.", reason="invalid_job_request")
        if arguments.get("repair"):
            prepared = self._plan_repair.prepare(arguments, intent)
            for scope_group in prepared.required_scope_groups:
                require_coach_scope(intent, *scope_group)
            manifest = self._plan_repair.execute(prepared)
            return self._plan_push.enqueue(
                manifest, sync_job_ids,
                reason=str(arguments.get("reason") or "Coach-Reparatur"), repair=True,
            )
        prepared = self._plan_sync.prepare(entries, intent)
        for scope_group in prepared.required_scope_groups:
            require_coach_scope(intent, *scope_group)
        return self._plan_sync.execute(
            prepared, sync_job_ids, reason=str(arguments.get("reason") or "Coach-Anfrage")
        )

    def _sync_competitions(
        self, arguments: dict[str, Any], intent: dict[str, Any], sync_job_ids: list[str]
    ) -> dict[str, Any]:
        if "sync_competitions" not in authorized_operations(intent) or intent.get("target_system") != "intervals":
            raise AppError(403, "Die strukturierte Coach-Autorisierung erlaubt diesen Sync nicht.", reason="intent_scope_denied")
        require_coach_scope(intent, "local_competitions")
        approval_manifest = arguments.get("_approval_manifest")
        if not isinstance(approval_manifest, list):
            raise AppError(409, "Für den Wettkampf-Sync fehlt die bestätigte Vorschau.")
        manifest = self._authority.mark_competitions_authoritative(approval_manifest)
        if not isinstance(manifest, list):
            raise AppError(500, "Die bestätigte Wettkampf-Vorschau ist ungültig.")
        job = self._queue.enqueue(
            "intervals", "competition_push",
            {
                "reason": str(arguments.get("reason") or "Bestätigter Coach-Auftrag"),
                "approval_manifest": manifest,
            },
            requested_by="coach",
        )
        sync_job_ids.append(job["id"])
        return {"ok": True, "status": "queued", "sync_job_id": job["id"]}

    def _resolve_conflict(
        self, arguments: dict[str, Any], intent: dict[str, Any], sync_job_ids: list[str]
    ) -> dict[str, Any]:
        if "resolve_training_sync_conflict" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")
        local_id = str(arguments.get("local_id") or "").strip()
        if local_id:
            require_coach_scope(intent, f"planned_unit:{local_id}", f"competition:{local_id}")
            return self._conflicts.resolve_local(
                local_id, str(arguments.get("strategy") or "keep_local").strip().casefold()
            )
        job_id = str(arguments.get("job_id") or "").strip()
        require_coach_scope(intent, f"sync_job:{job_id}")
        previous_job = self._conflicts.job_state(job_id)
        provider = previous_job["provider"]
        push = self._conflicts.is_push_job(previous_job)
        require_coach_scope(intent, "intervals_sync" if push else f"{provider}_refresh")
        if intent.get("target_system") != provider or bool((intent.get("request") or {}).get("remote_write")) != push:
            raise AppError(403, "Die Wiederholung benötigt den passenden Anbieterauftrag.", reason="request_target")
        result = self._conflicts.retry_job(job_id)
        sync_job_ids.append(job_id)
        return result

    def _delete_duplicate_activity(
        self, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        if "delete_duplicate_intervals_activity" not in authorized_operations(intent) or intent.get("target_system") != "intervals":
            raise AppError(403, "Die strukturierte Coach-Autorisierung erlaubt diesen Sync nicht.", reason="intent_scope_denied")
        require_coach_scope(intent, "intervals_sync")
        if not self._duplicate_activity or not self._intervals_client_factory:
            raise AppError(500, "Duplikat-Bereinigung ist nicht verfuegbar.")
        snapshot = self._duplicate_activity._latest_snapshot() or {}
        duplicate = latest_wahoo_garmin_duplicate(snapshot)
        if not duplicate:
            return {"ok": False, "status": "no_duplicate_found", "message": "Kein Wahoo-/Garmin-Duplikat vorhanden."}
        payload = {
            "canonical_id": str(arguments.get("canonical_id") or duplicate["canonical_id"]),
            "duplicate_id": str(arguments.get("duplicate_id") or duplicate["duplicate_id"]),
            "snapshot_synced_at": duplicate.get("snapshot_synced_at"),
        }
        result = self._duplicate_activity.delete(payload, self._intervals_client_factory())
        return {"ok": True, **result}
