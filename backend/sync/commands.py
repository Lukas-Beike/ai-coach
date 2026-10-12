"""Coach commands that queue or synchronously start provider refreshes.

A refresh is queued asynchronously unless tool preparation marked it as waiting
for completion. A waiting refresh runs inline through the ``SynchronousRefresh``
registered for its provider; a provider without one cannot wait.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.providers.descriptors import INTERVALS_ID
from backend.sync.garmin_service import GARMIN_AUTOMATIC_SYNC_DAYS, GarminSyncService
from backend.sync.intervals import IntervalsSyncService
from backend.sync.provider_runtime import SynchronousRefresh
from backend.sync.queue import SyncJobQueueService

MAX_REFRESH_DAYS = 3660


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
        _raise_if_busy(result, "Intervals.icu")
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
        if (
            activity_days != self._all_sync_days
            and not 1 <= activity_days <= MAX_REFRESH_DAYS
        ):
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
        _raise_if_busy(result, "Intervals.icu")
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


def _raise_if_busy(result: Mapping[str, Any], provider_label: str) -> None:
    if result.get("status") == "already_running":
        raise AppError(
            503,
            f"Die aktuelle {provider_label}-Synchronisierung ist noch nicht abgeschlossen.",
            reason="provider_busy",
        )


class GarminSynchronousRefresh:
    """Runs the Garmin refresh inline for a Coach request that waits.

    The Coach's ``days`` argument sets the window, as for a queued refresh;
    without it the scheduled catch-up window applies.
    """

    def __init__(
        self,
        garmin_sync_service: GarminSyncService,
        morning_body_battery_service: MorningBodyBatteryService,
    ) -> None:
        self._garmin_sync_service = garmin_sync_service
        self._morning_body_battery_service = morning_body_battery_service

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        days, end_date = self._window(arguments)
        result = self._sync(provider, days, end_date, True, cancel_event)
        if result.get("waited_for_existing"):
            # The awaited run may have covered another window or ended partial.
            result = self._sync(provider, days, end_date, False, cancel_event)
        status = result.get("status")
        if status in {"ok", "partial"}:
            self._morning_body_battery_service.refresh()
        return {
            "ok": True,
            "status": "completed",
            "provider": provider,
            "activity_days": days,
            "partial": status == "partial",
            "synchronous_refresh": True,
        }

    def _window(self, arguments: Mapping[str, Any]) -> tuple[int, date | None]:
        requested_days: Any = arguments.get("days")
        if requested_days is None:
            return self._garmin_sync_service.automatic_sync_window(
                GARMIN_AUTOMATIC_SYNC_DAYS
            )
        try:
            days = int(requested_days)
        except (TypeError, ValueError) as exc:
            raise AppError(
                400,
                "Der Garmin-Abruf benötigt einen gültigen Zeitraum.",
                reason="invalid_refresh_request",
            ) from exc
        if not 1 <= days <= MAX_REFRESH_DAYS:
            raise AppError(
                400,
                "Der Synchronisationszeitraum ist zu groß.",
                reason="invalid_refresh_request",
            )
        return days, None

    def _sync(
        self,
        provider: str,
        days: int,
        end_date: date | None,
        wait_for_existing: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        result = self._garmin_sync_service.sync(
            days=days,
            reason="Chat-Anfrage",
            end_date=end_date,
            wait_for_existing=wait_for_existing,
            cancel_event=cancel_event,
            include_recovery=True,
        )
        _raise_if_busy(result, provider)
        return result


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
