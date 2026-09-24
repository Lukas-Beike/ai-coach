"""Coach commands that queue or synchronously start provider refreshes."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from backend.errors import AppError
from backend.sync.intervals import IntervalsSyncService
from backend.sync.queue import SyncJobQueueService


class ProviderRefreshCommandService:
    """Orchestrate refresh commands after the Coach has authorized them."""

    def __init__(
        self,
        queue_service: SyncJobQueueService,
        intervals_sync_service: IntervalsSyncService,
        all_sync_days: int,
    ) -> None:
        self._queue_service = queue_service
        self._intervals_sync_service = intervals_sync_service
        self._all_sync_days = all_sync_days

    def start(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Queue an asynchronous refresh or perform the requested Intervals read."""
        wait_for_completion = bool(arguments.get("_wait_for_completion", False))
        if not wait_for_completion:
            job = self._queue_service.enqueue(
                provider,
                "refresh",
                {key: value for key, value in arguments.items() if key != "_wait_for_completion"},
                requested_by="coach",
            )
            return {"ok": True, "status": "queued", "sync_job_id": job["id"]}
        if provider != "intervals":
            raise AppError(
                400,
                "Ein synchroner Vorababruf ist nur fuer Intervals.icu zulaessig.",
                reason="invalid_refresh_request",
            )

        activity_days = self._activity_days(arguments)
        result = self._intervals_sync_service.sync(
            "Chat-Anfrage",
            activity_days=activity_days,
            wait_for_existing=True,
            wait_for_performance=True,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        self._raise_if_busy(result)
        try:
            completed_days = int(result.get("activity_days"))
        except (TypeError, ValueError):
            completed_days = 0

        if result.get("waited_for_existing") and not self._covers_window(
            completed_days, activity_days
        ):
            result = self._retry_intervals_refresh(activity_days, cancel_event)
            try:
                completed_days = int(result.get("activity_days"))
            except (TypeError, ValueError):
                completed_days = activity_days

        return {
            "ok": True,
            "status": "completed",
            "provider": provider,
            "activity_days": completed_days,
            "synchronous_refresh": True,
        }

    def queue_performance_refresh(
        self, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        job = self._queue_service.enqueue(
            "intervals",
            "performance_refresh",
            {"reason": str(arguments.get("reason") or "Coach-Anfrage")},
            requested_by="coach",
        )
        return {"ok": True, "status": "queued", "sync_job_id": job["id"]}

    def _activity_days(self, arguments: Mapping[str, Any]) -> int:
        try:
            activity_days = int(arguments.get("days"))
        except (TypeError, ValueError) as exc:
            raise AppError(
                400,
                "Der synchrone Aktivitaetsabruf benoetigt einen gueltigen Zeitraum.",
                reason="invalid_refresh_request",
            ) from exc
        if activity_days != self._all_sync_days and not 1 <= activity_days <= 3660:
            raise AppError(
                400,
                "Der Synchronisationszeitraum ist zu gross.",
                reason="invalid_refresh_request",
            )
        return activity_days

    def _retry_intervals_refresh(
        self, activity_days: int, cancel_event: threading.Event | None
    ) -> dict[str, Any]:
        result = self._intervals_sync_service.sync(
            "Chat-Anfrage",
            activity_days=activity_days,
            wait_for_existing=False,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        self._raise_if_busy(result)
        return result

    @staticmethod
    def _raise_if_busy(result: Mapping[str, Any]) -> None:
        if result.get("status") == "already_running":
            raise AppError(
                503,
                "Die aktuelle Intervals.icu-Synchronisierung ist noch nicht abgeschlossen.",
                reason="provider_busy",
            )

    def _covers_window(self, completed_days: int, requested_days: int) -> bool:
        return (
            completed_days == self._all_sync_days and requested_days >= 1
        ) or (
            requested_days == self._all_sync_days
            and completed_days == self._all_sync_days
        ) or (requested_days >= 1 and completed_days >= requested_days)
