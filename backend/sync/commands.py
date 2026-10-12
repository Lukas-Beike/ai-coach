"""Coach commands that queue or synchronously start provider refreshes.

A refresh is queued asynchronously unless tool preparation marked it as waiting
for completion. A waiting refresh runs inline through the ``SynchronousRefresh``
registered for its provider; a provider without one cannot wait.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from backend.errors import AppError
from backend.providers.descriptors import INTERVALS_ID
from backend.sync.intervals import IntervalsSyncService
from backend.sync.provider_runtime import SynchronousRefresh
from backend.sync.queue import SyncJobQueueService


class IntervalsSynchronousRefresh:
    """Waits for the running Intervals.icu sync or starts one for a Coach request."""

    def __init__(
        self, intervals_sync_service: IntervalsSyncService, all_sync_days: int
    ) -> None:
        self._intervals_sync_service = intervals_sync_service
        self._all_sync_days = all_sync_days

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        activity_days = self._activity_days(arguments)
        result = self._intervals_sync_service.sync(
            "Chat-Anfrage",
            activity_days=activity_days,
            wait_for_existing=True,
            wait_for_performance=True,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        _raise_if_busy(result)
        try:
            completed_days = int(result.get("activity_days"))
        except TypeError, ValueError:
            completed_days = 0

        if result.get("waited_for_existing") and not self._covers_window(
            completed_days, activity_days
        ):
            result = self._retry_intervals_refresh(activity_days, cancel_event)
            retried_days: Any = result.get("activity_days")
            try:
                completed_days = int(retried_days)
            except TypeError, ValueError:
                completed_days = activity_days

        return {
            "ok": True,
            "status": "completed",
            "provider": provider,
            "activity_days": completed_days,
            "synchronous_refresh": True,
        }

    def _activity_days(self, arguments: Mapping[str, Any]) -> int:
        requested_days: Any = arguments.get("days")
        try:
            activity_days = int(requested_days)
        except (TypeError, ValueError) as exc:
            raise AppError(
                400,
                "Der synchrone Aktivitätsabruf benötigt einen gültigen Zeitraum.",
                reason="invalid_refresh_request",
            ) from exc
        if activity_days != self._all_sync_days and not 1 <= activity_days <= 3660:
            raise AppError(
                400,
                "Der Synchronisationszeitraum ist zu groß.",
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
        _raise_if_busy(result)
        return result

    def _covers_window(self, completed_days: int, requested_days: int) -> bool:
        return (
            (completed_days == self._all_sync_days and requested_days >= 1)
            or (
                requested_days == self._all_sync_days
                and completed_days == self._all_sync_days
            )
            or (requested_days >= 1 and completed_days >= requested_days)
        )


def _raise_if_busy(result: Mapping[str, Any]) -> None:
    if result.get("status") == "already_running":
        raise AppError(
            503,
            "Die aktuelle Intervals.icu-Synchronisierung ist noch nicht abgeschlossen.",
            reason="provider_busy",
        )


class ProviderRefreshCommandService:
    """Orchestrate refresh commands after the Coach has authorized them.

    ``synchronous_refreshes`` maps provider ids to the inline refresh used when a
    request waits for completion. ``None`` keeps the Intervals.icu default.
    """

    def __init__(
        self,
        queue_service: SyncJobQueueService,
        intervals_sync_service: IntervalsSyncService,
        all_sync_days: int,
        *,
        synchronous_refreshes: Mapping[str, SynchronousRefresh] | None = None,
    ) -> None:
        self._queue_service = queue_service
        self._synchronous_refreshes: Mapping[str, SynchronousRefresh] = (
            {
                INTERVALS_ID: IntervalsSynchronousRefresh(
                    intervals_sync_service, all_sync_days
                )
            }
            if synchronous_refreshes is None
            else synchronous_refreshes
        )

    def start(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Queue an asynchronous refresh or run the provider's synchronous refresh."""
        wait_for_completion = bool(arguments.get("_wait_for_completion", False))
        if not wait_for_completion:
            job = self._queue_service.enqueue(
                provider,
                "refresh",
                {
                    key: value
                    for key, value in arguments.items()
                    if key != "_wait_for_completion"
                },
                requested_by="coach",
            )
            return {"ok": True, "status": "queued", "sync_job_id": job["id"]}
        synchronous = self._synchronous_refreshes.get(provider)
        if synchronous is None:
            raise AppError(
                400,
                "Für diesen Anbieter ist kein synchroner Vorababruf verfügbar.",
                reason="invalid_refresh_request",
            )
        return synchronous.refresh(provider, arguments, cancel_event)

    def queue_performance_refresh(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        job = self._queue_service.enqueue(
            INTERVALS_ID,
            "performance_refresh",
            {"reason": str(arguments.get("reason") or "Coach-Anfrage")},
            requested_by="coach",
        )
        return {"ok": True, "status": "queued", "sync_job_id": job["id"]}
