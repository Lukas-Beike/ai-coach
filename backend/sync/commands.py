"""Coach commands that queue or synchronously start provider refreshes.

A refresh is queued asynchronously unless tool preparation marked it as waiting
for completion. A waiting refresh runs inline through the ``SynchronousRefresh``
registered for its provider; a provider without one cannot wait.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminSyncService,
    refresh_morning_battery_after_sync,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import SynchronousRefresh
from backend.sync.queue import SyncJobQueueService
from backend.sync.wahoo_sync import WahooSyncService


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


# Days a waiting Coach refresh reads from Wahoo when it names no usable window.
WAHOO_COACH_REFRESH_DAYS = 7


class WahooSynchronousRefresh:
    """Runs the Wahoo workout refresh inline for a Coach request that waits.

    A scheduled or manual run that holds the Wahoo lock is awaited for up to
    ``wait_seconds`` before this request reads; a cancelled request never starts
    a read. Like the Garmin refresh it reads a short catch-up window: no ``days``
    or the whole-history sentinel use ``WAHOO_COACH_REFRESH_DAYS`` and an
    explicit window is kept, both bounded by the stored Wahoo sync period
    (``stored_days``). A partial read is reported as ``partial`` and an
    unconnected Wahoo account fails the refresh.
    """

    def __init__(
        self,
        wahoo_sync_service: WahooSyncService,
        all_sync_days: int,
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
        wait_seconds: float = 120.0,
        stored_days: Callable[[], int] | None = None,
    ) -> None:
        self._stored_days = stored_days
        self._wahoo_sync_service = wahoo_sync_service
        self._all_sync_days = all_sync_days
        self._registry = registry
        self._wait_seconds = wait_seconds

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        requested_days: Any = arguments.get("days")
        days = (
            None
            if requested_days is None
            else _requested_days(
                requested_days, provider, self._all_sync_days, self._registry
            )
        )
        label = self._registry.get(provider).label
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
        # The sync acquires the lock itself, waiting for a running read to end.
        result = self._wahoo_sync_service.sync(
            self._window(days),
            "Chat-Anfrage",
            wait_seconds=self._wait_seconds,
            cancel_event=cancel_event,
        )
        if (
            result.get("status") == "already_running"
            and cancel_event is not None
            and cancel_event.is_set()
        ):
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
        _raise_if_busy(result, label)
        status = result.get("status")
        if status == "not_configured":
            raise AppError(
                503,
                str(result.get("message") or f"{label} ist nicht verbunden."),
                reason="not_configured",
            )
        if status not in {"ok", "partial"}:
            raise AppError(
                503,
                f"Die {label}-Aktualisierung lieferte kein verwertbares Ergebnis.",
                reason="provider_refresh_failed",
            )
        return {
            "ok": True,
            "status": "completed",
            "provider": provider,
            "partial": status == "partial",
            "synchronous_refresh": True,
        }

    def _window(self, days: int | None) -> int:
        """Return the short catch-up window, bounded by the stored sync period."""
        if days is None or days == self._all_sync_days:
            window = WAHOO_COACH_REFRESH_DAYS
        else:
            window = days
        if self._stored_days is None:
            return window
        stored = self._stored_days()
        return window if stored == self._all_sync_days else max(1, min(window, stored))


class ProviderRefreshCommandService:
    """Orchestrate refresh commands after the Coach has authorized them.

    ``synchronous_refreshes`` maps provider ids to the inline refresh used when a
    request waits for completion. ``after_refresh`` is the completion hook a
    queued job runs (the derived passes); a finished inline refresh runs it too.
    """

    def __init__(
        self,
        queue_service: SyncJobQueueService,
        synchronous_refreshes: Mapping[str, SynchronousRefresh],
        after_refresh: Callable[[Mapping[str, Any]], None] = lambda _job: None,
    ) -> None:
        self._queue_service = queue_service
        self._synchronous_refreshes = synchronous_refreshes
        self._after_refresh = after_refresh

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
        result = synchronous.refresh(provider, arguments, cancel_event)
        self._after_refresh({"provider": provider, "type": "refresh"})
        return result
