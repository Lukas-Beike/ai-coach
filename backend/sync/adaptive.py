"""Adaptive remote calendar synchronization use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from backend.athlete.checkins import CHECKIN_TEXT_LIMITS
from backend.calendar.canonical import ISO_MIDNIGHT_SUFFIX
from backend.config import Config
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.observability import Redactor
from backend.planning import adaptive as planning_adaptive
from backend.planning.adaptive import AdaptiveReplanApplyService
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.competition_service import CompetitionService
from backend.planning.season import planning_state

ILLNESS_CALENDAR_CATEGORY = "SICK"
ILLNESS_EVENT_EXTERNAL_PREFIX = "intervals-coach-sick-"


class _CalendarEventWriter(Protocol):
    def upsert_calendar_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


class AdaptivePreviewFollowupService:
    """Recalculate a local adaptive preview after a provider refresh."""

    def __init__(
        self,
        preview_service: AdaptiveReplanPreviewService,
        logger: logging.Logger,
    ) -> None:
        self._preview_service = preview_service
        self._logger = logger

    def check(self, reason: str) -> dict[str, Any]:
        try:
            preview = self._preview_service.preview()
            changes = preview.get("changes", []) if isinstance(preview, dict) else []
            return {
                "needs_replan": bool(changes),
                "replan_changes": len(changes) if isinstance(changes, list) else 0,
            }
        except Exception:
            self._logger.warning(
                "Adaptive preview after provider sync failed",
                extra={
                    "event": "adaptive_replan_preview_failed",
                    "context": {"reason": reason},
                },
                exc_info=True,
            )
            return self._preview_service.status()


class IllnessPauseSyncService:
    """Coordinate local adaptive replans and explicitly requested illness sync."""

    def __init__(
        self,
        config: Config,
        calendar_event_writer: _CalendarEventWriter,
        *,
        adaptive_replan_apply_service: AdaptiveReplanApplyService | None = None,
        competition_service: CompetitionService | None = None,
        adaptive_replan_preview_service: AdaptiveReplanPreviewService | None = None,
        redactor: Redactor | None = None,
        today: Callable[[], date] | None = None,
    ):
        self._config = config
        self._calendar_event_writer = calendar_event_writer
        self._adaptive_replan_apply_service = adaptive_replan_apply_service
        self._competition_service = competition_service
        self._adaptive_replan_preview_service = adaptive_replan_preview_service
        self._redactor = redactor
        self._today = today

    def sync(self, pause: dict[str, Any]) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)

        illness = str(pause.get("illness") or "Krankheit").strip()[
            : CHECKIN_TEXT_LIMITS["illness"]
        ]
        events = planning_adaptive.illness_calendar_events(
            pause,
            illness,
            category=ILLNESS_CALENDAR_CATEGORY,
            external_prefix=ILLNESS_EVENT_EXTERNAL_PREFIX,
            midnight_suffix=ISO_MIDNIGHT_SUFFIX,
        )
        pushed = self._calendar_event_writer.upsert_calendar_events(events)
        return {
            "status": "ok",
            "synced": len(pushed),
            "category": ILLNESS_CALENDAR_CATEGORY,
        }

    def apply(
        self, adjustment_id: Any, *, sync_illness_to_intervals: bool = False
    ) -> dict[str, Any]:
        """Apply the local preview, then optionally write its illness pause remotely."""
        if (
            self._adaptive_replan_apply_service is None
            or self._competition_service is None
            or self._adaptive_replan_preview_service is None
            or self._redactor is None
            or self._today is None
        ):
            raise RuntimeError("Adaptive replan dependencies were not configured.")

        applied = self._adaptive_replan_apply_service.apply(adjustment_id)
        status = applied["status"]
        if status.startswith("already_"):
            return applied

        illness_pause = applied["illness_pause"]
        active_illness_pause = (
            illness_pause
            if illness_pause and not illness_pause.get("approved")
            else None
        )
        remote_sync: dict[str, Any] | None = None
        if sync_illness_to_intervals and active_illness_pause:
            try:
                remote_sync = self.sync(active_illness_pause)
            except Exception as exc:
                remote_sync = {
                    "status": "error",
                    "error": self._redactor.redact_text(str(exc))[:1000],
                }

        result = {
            "status": status if applied["stale"] else "ok",
            "id": applied["id"],
            "updated": applied["updated"],
            "updated_checkins": applied["updated_checkins"],
            "illness_pause": illness_pause,
            "intervals_sync": remote_sync,
            "planning": planning_state(
                self._competition_service.list(),
                self._today(),
                self._adaptive_replan_preview_service.latest_preview(),
                self._adaptive_replan_preview_service.status(),
            ),
        }
        if applied["stale"]:
            result.update(
                {
                    "stale": applied["stale"],
                    "message": "Die Vorschau war teilweise oder vollständig veraltet; die betroffenen Einheiten wurden nicht überschrieben.",
                }
            )
        return result
