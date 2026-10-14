"""Authorize an adaptive Coach application after a separately published preview."""

from __future__ import annotations

from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.coach.authorization import (
    authorized_operations,
    require_coach_scope,
    scope_values,
)
from backend.db.manager import DatabaseManager
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.sync.adaptive import IllnessPauseSyncService


class CoachAdaptiveApplyService:
    """Own the authorization and next-message approval boundary for adaptive apply.

    The write gate's classifier confirms that the athlete's message asks to apply
    the change; this service enforces that it is the first athlete message after
    the preview was published, so no later message can approve an older preview.
    """

    def __init__(
        self,
        preview: AdaptiveReplanPreviewService,
        illness_sync: IllnessPauseSyncService,
        database_manager: DatabaseManager,
        database_lock: Any,
    ) -> None:
        self._preview = preview
        self._illness_sync = illness_sync
        self._database_manager = database_manager
        self._database_lock = database_lock

    def apply(
        self,
        arguments: dict[str, Any],
        intent: dict[str, Any],
        client_turn_id: str,
    ) -> dict[str, Any]:
        if "apply_adaptive_replan" not in authorized_operations(intent):
            raise AppError(
                403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied"
            )
        adjustment_id = str(arguments.get("adjustment_id") or "").strip()
        require_coach_scope(
            intent, f"adaptive_replan:{adjustment_id}", "adaptive_replan"
        )
        sync_illness = bool(arguments.get("sync_illness_to_intervals"))
        if sync_illness and (
            intent.get("target_system") != ProviderId.INTERVALS
            or "intervals_sync" not in scope_values(intent)
        ):
            raise AppError(
                403,
                "Der Intervals.icu-Sync der Krankheitspause muss ausdrücklich benannt werden.",
                reason="intent_scope_denied",
            )
        latest = self._preview.latest_preview()
        if (
            not latest
            or str(latest.get("id")) != adjustment_id
            or latest.get("status") != "preview"
        ):
            raise AppError(
                409, "Bitte zuerst die aktuelle adaptive Planungsvorschau erstellen."
            )
        with self._database_lock, self._database_manager.unit_of_work() as db:
            current_user = db.execute(
                "SELECT id FROM messages WHERE client_turn_id=? AND role='user'",
                (client_turn_id,),
            ).fetchone()
            publication = db.execute(
                "SELECT id FROM messages WHERE id=? AND role='assistant'",
                (latest.get("published_message_id"),),
            ).fetchone()
            first_reply = (
                db.execute(
                    "SELECT MIN(id) AS id FROM messages WHERE role='user' AND id>?",
                    (publication["id"],),
                ).fetchone()
                if publication
                else None
            )
        if (
            not current_user
            or not first_reply
            or current_user["id"] != first_reply["id"]
            or current_user["id"]
            not in (intent.get("request") or {}).get("source_message_ids", [])
        ):
            raise AppError(
                403,
                "Die Vorschau muss zuerst angezeigt und in der darauf folgenden "
                "Nachricht ausdrücklich freigegeben werden. Bitte eine neue Vorschau "
                "erstellen und erneut fragen.",
                reason="adaptive_approval_required",
            )
        return {
            "ok": True,
            **self._illness_sync.apply(
                adjustment_id, sync_illness_to_intervals=sync_illness
            ),
        }
