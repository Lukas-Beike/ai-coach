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
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminSyncService,
    refresh_morning_battery_after_sync,
)
from backend.sync.intervals import IntervalsSyncService
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import SynchronousRefresh
from backend.sync.queue import SyncJobQueueService


class IntervalsSynchronousRefresh:
    """Waits for the running Intervals.icu sync or starts one for a Coach request.

    Without a ``days`` argument the refresh reads the stored sync period, as a
    queued refresh does; that period is clamped when it is stored. The
    provider's sync-window limit bounds an explicit ``days`` argument.
    """

    def __init__(
        self,
        intervals_sync_service: IntervalsSyncService,
        all_sync_days: int,
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._intervals_sync_service = intervals_sync_service
        self._all_sync_days = all_sync_days
        self._registry = registry

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        activity_days = self._activity_days(provider, arguments)
        result = self._intervals_sync_service.sync(
            "Chat-Anfrage",
            activity_days=activity_days,
            wait_for_existing=True,
            wait_for_performance=True,
            **_cancel_kwargs(cancel_event),
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

    def _activity_days(self, provider: str, arguments: Mapping[str, Any]) -> int:
        requested_days: Any = arguments.get("days")
        if requested_days is None:
            return self._intervals_sync_service.sync_period()
        return _requested_days(
            requested_days, provider, self._all_sync_days, self._registry
        )

    def _retry_intervals_refresh(
        self, activity_days: int, cancel_event: threading.Event | None
    ) -> dict[str, Any]:
        result = self._intervals_sync_service.sync(
            "Chat-Anfrage",
            activity_days=activity_days,
            wait_for_existing=False,
            **_cancel_kwargs(cancel_event),
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


def _requested_days(
    requested_days: Any, provider: str, all_sync_days: int, registry: ProviderRegistry
) -> int:
    """Validate a Coach refresh window; ``all_sync_days`` marks the whole history.

    The registry's rule is the one a stored sync period must satisfy as well.
    """
    try:
        days = int(requested_days)
    except (TypeError, ValueError) as exc:
        raise AppError(
            400,
            "Der synchrone Datenabruf benötigt einen gültigen Zeitraum.",
            reason="invalid_refresh_request",
        ) from exc
    if not registry.accepts_sync_days(provider, days, all_sync_days):
        raise AppError(
            400,
            "Der Synchronisationszeitraum ist zu groß.",
            reason="invalid_refresh_request",
        )
    return days


def _cancel_kwargs(cancel_event: threading.Event | None) -> dict[str, Any]:
    return {"cancel_event": cancel_event} if cancel_event is not None else {}


def _raise_if_busy(result: Mapping[str, Any], provider_label: str) -> None:
    if result.get("status") == "already_running":
        raise AppError(
            503,
            f"Die aktuelle {provider_label}-Synchronisierung ist noch nicht abgeschlossen.",
            reason="provider_busy",
        )


class GarminSynchronousRefresh:
    """Runs the Garmin refresh inline for a Coach request that waits.

    The Coach's ``days`` argument sets the window, as for a queued refresh. The
    whole-history sentinel, or no window, uses the scheduled catch-up window:
    an inline chat refresh cannot read the full history, and a historical
    backfill stays a queued job. The result flags a narrowed whole-history
    request as ``history_limited``. A catch-up window that ends before today,
    or an awaited run whose window could not be confirmed, makes the result
    ``partial``, as does a morning Body Battery refresh that failed, was busy
    or was cancelled. Only an ``ok`` or ``partial`` run counts as completed;
    any other outcome fails the refresh.
    """

    def __init__(
        self,
        garmin_sync_service: GarminSyncService,
        morning_body_battery_service: MorningBodyBatteryService,
        all_sync_days: int,
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._garmin_sync_service = garmin_sync_service
        self._morning_body_battery_service = morning_body_battery_service
        self._all_sync_days = all_sync_days
        self._registry = registry

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        days, end_date, history_limited = self._window(provider, arguments)
        label = self._registry.get(provider).label
        result = self._sync(days, end_date, True, cancel_event)
        _raise_if_busy(result, label)
        if result.get("waited_for_existing"):
            result = self._after_waiting(result, days, end_date, cancel_event)
        status = result.get("status")
        if status not in {"ok", "partial"}:
            raise AppError(
                503,
                f"Die {label}-Aktualisierung lieferte kein verwertbares Ergebnis.",
                reason="provider_refresh_failed",
            )
        battery_refreshed = refresh_morning_battery_after_sync(
            result, self._morning_body_battery_service, cancel_event
        )
        window_unconfirmed = bool(result.get("window_unconfirmed"))
        return {
            "ok": True,
            "status": "completed",
            "provider": provider,
            "activity_days": None if window_unconfirmed else days,
            "partial": status == "partial"
            or end_date is not None
            or not battery_refreshed,
            "history_limited": history_limited,
            "synchronous_refresh": True,
        }

    def _after_waiting(
        self,
        result: dict[str, Any],
        days: int,
        end_date: date | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        """Report the awaited run, or rerun when it did not read the window."""
        status = self._garmin_sync_service.awaited_run_status(
            days, end_date, result.get("synced_at")
        )
        if status is not None:
            return {**result, "status": status}
        rerun = self._sync(days, end_date, False, cancel_event)
        # A run that took the lock meanwhile leaves only the awaited data, whose
        # window is unknown.
        if rerun.get("status") == "already_running":
            return {"status": "partial", "window_unconfirmed": True}
        return rerun

    def _window(
        self, provider: str, arguments: Mapping[str, Any]
    ) -> tuple[int, date | None, bool]:
        """Return the window and whether it narrows a whole-history request."""
        requested_days: Any = arguments.get("days")
        days = (
            None
            if requested_days is None
            else _requested_days(
                requested_days, provider, self._all_sync_days, self._registry
            )
        )
        if days is None or days == self._all_sync_days:
            window_days, end_date = self._garmin_sync_service.automatic_sync_window(
                GARMIN_AUTOMATIC_SYNC_DAYS
            )
            return window_days, end_date, days is not None
        return days, None, False

    def _sync(
        self,
        days: int,
        end_date: date | None,
        wait_for_existing: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        return self._garmin_sync_service.sync(
            days=days,
            reason="Chat-Anfrage",
            end_date=end_date,
            wait_for_existing=wait_for_existing,
            cancel_event=cancel_event,
            include_recovery=True,
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
