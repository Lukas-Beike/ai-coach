"""Persistence for post-fetch Intervals.icu synchronization work."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from backend.activities.duplicates import deduplicate_api_records
from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import (
    COACH_ABORTED_ERROR,
    INTERVALS_API_KEY_ERROR,
    AppError,
)
from backend.planning.context import compact_snapshot
from backend.planning.library_service import WorkoutLibraryService
from backend.providers.intervals import IntervalsApiClient
from backend.sync.daily import DailySyncMarkerService
from backend.sync.gates import ProviderResyncGate
from backend.sync.library import WorkoutLibraryRefreshService
from backend.sync.observation import SyncOperationObserver
from backend.sync.performance import PerformanceRefreshFollowupService
from backend.sync.planned_units import RemotePlannedUnitReconciler
from backend.sync.snapshots import merge_historical_snapshot
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncOperationStateWriter
from backend.sync.windows import split_date_windows


class IntervalsSnapshotReader:
    """Read Intervals provider data and prepare complete durable snapshots."""

    def __init__(
        self,
        config: Config,
        api_client: IntervalsApiClient,
        sync_state_repository: SyncStateRepository,
        local_now: Callable[[], datetime],
        utc_now: Callable[[], str],
        earliest_date: date,
        chunk_days: int,
        all_sync_days: int,
        calendar_history_days: int,
        calendar_future_days: int,
    ) -> None:
        self._config = config
        self._api_client = api_client
        self._sync_state_repository = sync_state_repository
        self._local_now = local_now
        self._utc_now = utc_now
        self._earliest_date = earliest_date
        self._chunk_days = chunk_days
        self._all_sync_days = all_sync_days
        self._calendar_history_days = calendar_history_days
        self._calendar_future_days = calendar_future_days

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")

    @staticmethod
    def _cancel_kwargs(cancel_event: threading.Event | None) -> dict[str, Any]:
        return {"cancel_event": cancel_event} if cancel_event is not None else {}

    def _pagination(self) -> dict[str, dict[str, Any]]:
        return {
            collection: dict(metadata)
            for collection, metadata in self._api_client.pagination.items()
        }

    def fetch_snapshot(
        self,
        activity_days: int = 42,
        end_date: date | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        athlete = quote(self._config.intervals_athlete_id, safe="")
        today = end_date or self._local_now().date()
        calendar_start = today - timedelta(days=self._calendar_history_days)
        calendar_end = today + timedelta(days=self._calendar_future_days)
        existing = self._sync_state_repository.latest_snapshot() or {}
        incremental = bool(existing) and activity_days != self._all_sync_days
        request_days = activity_days
        activities: list[Any] = []
        wellness: list[Any] = []
        cancel_kwargs = self._cancel_kwargs(cancel_event)

        for window_start, window_end in split_date_windows(
            request_days,
            end_date=today,
            earliest_date=self._earliest_date,
            chunk_days=self._chunk_days,
            all_days=self._all_sync_days,
        ):
            range_params = {
                "oldest": window_start.isoformat(),
                "newest": window_end.isoformat(),
            }
            self._raise_if_cancelled(cancel_event)
            activities.extend(
                self._api_client.get_paged_collection(
                    f"/athlete/{athlete}/activities",
                    range_params,
                    "activities",
                    **cancel_kwargs,
                )
            )
            self._raise_if_cancelled(cancel_event)
            wellness.extend(
                self._api_client.get_paged_collection(
                    f"/athlete/{athlete}/wellness",
                    range_params,
                    "wellness",
                    **cancel_kwargs,
                )
            )

        activities = deduplicate_api_records(activities)
        wellness = deduplicate_api_records(wellness)
        self._raise_if_cancelled(cancel_event)
        events = self._api_client.get_paged_collection(
            f"/athlete/{athlete}/events",
            {
                "oldest": calendar_start.isoformat(),
                "newest": calendar_end.isoformat(),
            },
            "events",
            **cancel_kwargs,
        )
        self._raise_if_cancelled(cancel_event)
        athlete_data = self._api_client.get(f"/athlete/{athlete}", **cancel_kwargs)
        incoming = compact_snapshot(
            athlete_data,
            activities,
            wellness,
            events,
            history_days=request_days,
            all_sync_days=self._all_sync_days,
            synced_at=self._utc_now(),
        )
        # Keep every provider row in durable storage; only the compact fields
        # above are the read model passed on to consumers.
        incoming["raw_provider_data"] = {
            "athlete": athlete_data if isinstance(athlete_data, dict) else {},
            "activities": activities,
            "wellness": wellness,
            "upcoming_calendar": events,
        }
        incoming["provider_sync"] = {
            "pagination": self._pagination(),
            "calendar_window": {
                "start": calendar_start.isoformat(),
                "end": calendar_end.isoformat(),
            },
        }
        if not incremental:
            return incoming

        merged = dict(incoming)
        merged["recent_activities"] = deduplicate_api_records(
            incoming["recent_activities"] + existing.get("recent_activities", [])
        )[:500]
        merged["recent_wellness"] = deduplicate_api_records(
            incoming["recent_wellness"] + existing.get("recent_wellness", [])
        )[-(max(42, activity_days) + 1) :]
        previous_raw = (
            existing.get("raw_provider_data")
            if isinstance(existing.get("raw_provider_data"), dict)
            else {}
        )
        merged["raw_provider_data"] = {
            "athlete": incoming["raw_provider_data"]["athlete"],
            "activities": deduplicate_api_records(
                incoming["raw_provider_data"]["activities"]
                + (previous_raw.get("activities") or [])
            ),
            "wellness": deduplicate_api_records(
                incoming["raw_provider_data"]["wellness"]
                + (previous_raw.get("wellness") or [])
            ),
            "upcoming_calendar": incoming["raw_provider_data"]["upcoming_calendar"],
        }
        merged["incremental"] = True
        merged["incremental_window_days"] = request_days
        return merged

    def fetch_performance_snapshot(
        self, existing_snapshot: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Refresh athlete settings and 90-day wellness without other collections."""
        athlete = quote(self._config.intervals_athlete_id, safe="")
        today = self._local_now().date()
        wellness_start = today - timedelta(days=90)
        athlete_data = self._api_client.get(f"/athlete/{athlete}")
        wellness = self._api_client.get_paged_collection(
            f"/athlete/{athlete}/wellness",
            {"oldest": wellness_start.isoformat(), "newest": today.isoformat()},
            "performance_wellness",
        )
        existing = existing_snapshot if isinstance(existing_snapshot, dict) else {}
        snapshot = compact_snapshot(
            athlete_data,
            existing.get("recent_activities", []),
            wellness,
            existing.get("upcoming_calendar", []),
            history_days=90,
            all_sync_days=self._all_sync_days,
            synced_at=self._utc_now(),
        )
        snapshot["provider_sync"] = {"pagination": self._pagination()}
        snapshot["raw_provider_data"] = {
            "athlete": athlete_data,
            "wellness": wellness,
        }
        return snapshot


class IntervalsSnapshotService:
    """Persist a fetched Intervals snapshot and its related local state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        sync_state_repository: SyncStateRepository,
        remote_planned_unit_reconciler: RemotePlannedUnitReconciler,
        workout_library_refresh_service: WorkoutLibraryRefreshService,
        workout_library_service: WorkoutLibraryService,
        redactor: Callable[[str], str],
        local_now: Callable[[], datetime],
        earliest_date: date,
        chunk_days: int,
        all_sync_days: int,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._sync_state_repository = sync_state_repository
        self._remote_planned_unit_reconciler = remote_planned_unit_reconciler
        self._workout_library_refresh_service = workout_library_refresh_service
        self._workout_library_service = workout_library_service
        self._redactor = redactor
        self._local_now = local_now
        self._earliest_date = earliest_date
        self._chunk_days = chunk_days
        self._all_sync_days = all_sync_days

    def store_snapshot(
        self, snapshot: dict[str, Any], activity_days: int, end_date: date | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if end_date is not None:
            snapshot = merge_historical_snapshot(
                self._sync_state_repository.latest_snapshot(), snapshot
            )
            self._sync_state_repository.save_snapshot(snapshot, update_full_sync=False)
        else:
            self._sync_state_repository.save_snapshot(
                snapshot, activity_days=activity_days
            )

        provider_sync = snapshot.get("provider_sync", {})
        calendar_window = (
            provider_sync.get("calendar_window", {})
            if isinstance(provider_sync, dict)
            else {}
        )
        planned_import = {"imported": 0, "updated": 0, "conflicts": 0}
        if end_date is None:
            # Nested service calls intentionally share this UOW: reconciliation
            # and its initial-import marker must roll back together.
            with self._database_manager.unit_of_work() as db:
                pending_repair = db.execute(
                    "SELECT 1 FROM sync_jobs WHERE provider='intervals' AND type='plan_push' "
                    "AND status IN ('queued', 'running') "
                    "AND json_extract(payload, '$.repair')=1 LIMIT 1"
                ).fetchone()
                if pending_repair:
                    planned_import["deferred_for_repair"] = True
                elif not self._key_value_repository.get(
                    db, "planned_units_initial_import_at"
                ):
                    planned_import = self._remote_planned_unit_reconciler.reconcile(
                        snapshot.get("upcoming_calendar", []),
                        calendar_start=calendar_window.get("start"),
                        calendar_end=calendar_window.get("end"),
                    )
                    self._key_value_repository.set(
                        db, "planned_units_initial_import_at", snapshot["synced_at"]
                    )
        return snapshot, planned_import

    def seed_workout_library(
        self, reason: str, cancel_event: threading.Event | None
    ) -> tuple[int, str | None, int]:
        library_imported = 0
        library_error = None
        with self._database_manager.unit_of_work() as db:
            needs_initial_refresh = not self._key_value_repository.get(
                db, "last_library_sync_at"
            )
        if needs_initial_refresh:
            try:
                kwargs = {"reason": f"Initialer Intervals.icu-Sync ({reason})"}
                if cancel_event is not None:
                    kwargs["cancel_event"] = cancel_event
                library_refresh = self._workout_library_refresh_service.refresh(
                    **kwargs
                )
                library_imported = int(library_refresh.get("workouts") or 0)
            except Exception as exc:
                if isinstance(exc, AppError) and exc.reason == "chat_cancelled":
                    raise
                library_error = self._redactor(str(exc))[:1000]
                self._set_key_value("last_library_sync_error", library_error)
        return (
            library_imported,
            library_error,
            len(self._workout_library_service.list()),
        )

    def _set_key_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    def record_window(
        self, activity_days: int, end_date: date | None, snapshot: dict[str, Any]
    ) -> tuple[list[tuple[date, date]], dict[str, Any]]:
        sync_window = split_date_windows(
            activity_days,
            end_date=end_date or self._local_now().date(),
            earliest_date=self._earliest_date,
            chunk_days=self._chunk_days,
            all_days=self._all_sync_days,
        )
        synced_at = snapshot["synced_at"]
        self._sync_state_repository.update_cursor(
            "intervals", "activities", sync_window[-1][1].isoformat(), synced_at
        )
        self._sync_state_repository.update_cursor(
            "intervals", "wellness", sync_window[-1][1].isoformat(), synced_at
        )
        if end_date is not None:
            self._sync_state_repository.update_cursor(
                "intervals", "historical", sync_window[0][0].isoformat(), synced_at
            )

        provider_sync = snapshot.get("provider_sync", {})
        pagination = (
            provider_sync.get("pagination", {})
            if isinstance(provider_sync, dict)
            else {}
        )
        self._set_key_value("last_sync_window_start", sync_window[0][0].isoformat())
        self._set_key_value("last_sync_window_end", sync_window[-1][1].isoformat())
        self._set_key_value("last_sync_activity_days", str(activity_days))
        self._set_key_value(
            "last_sync_pagination",
            json.dumps(pagination, ensure_ascii=False, separators=(",", ":")),
        )
        return sync_window, pagination


class IntervalsSyncWorkflow:
    """Own the reader, snapshot, pagination, and cursor steps of a sync."""

    def __init__(
        self,
        reader: IntervalsSnapshotReader,
        snapshots: IntervalsSnapshotService,
        state: SyncStateRepository,
        daily_sync_marker_service: DailySyncMarkerService,
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
    ) -> None:
        self._reader = reader
        self._snapshots = snapshots
        self._state = state
        self._daily_sync_marker_service = daily_sync_marker_service
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days

    @property
    def all_sync_days(self) -> int:
        return self._all_sync_days

    def sync_period(self) -> int:
        return self._state.sync_period(
            "intervals", self._sync_period_defaults, self._all_sync_days
        )

    def synchronize(
        self,
        reason: str,
        activity_days: int,
        end_date: date | None,
        cancel_event: threading.Event | None,
        operation_id: str,
        journal: IntervalsSyncJournal,
    ) -> dict[str, Any]:
        snapshot = self._reader.fetch_snapshot(
            activity_days=activity_days,
            **({"end_date": end_date} if end_date is not None else {}),
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        journal.storing(operation_id)
        snapshot, planned_import = self._snapshots.store_snapshot(
            snapshot, activity_days, end_date
        )
        if end_date is None:
            self._daily_sync_marker_service.mark("intervals")
        library_imported, library_error, library_count = (
            self._snapshots.seed_workout_library(reason, cancel_event)
        )
        sync_window, pagination = self._snapshots.record_window(
            activity_days, end_date, snapshot
        )
        return {
            "status": "partial" if library_error else "ok",
            "synced_at": snapshot["synced_at"],
            "activities": len(snapshot["recent_activities"]),
            "wellness": len(snapshot["recent_wellness"]),
            "events": len(snapshot["upcoming_calendar"]),
            "planned_import": planned_import,
            "activity_days": activity_days,
            "window_start": sync_window[0][0].isoformat(),
            "window_end": sync_window[-1][1].isoformat(),
            "library": library_count,
            "library_imported": library_imported,
            "library_error": library_error,
            "pagination": pagination,
        }


class IntervalsSyncStatus:
    """Own transactional reads and writes of Intervals sync KV state."""

    def __init__(
        self, database_manager: DatabaseManager, key_values: KeyValueRepository
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values

    def get(self, key: str) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_values.get(db, key)

    def set(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_values.set(db, key, value)


class IntervalsSyncJournal:
    """Own operation progress, failure redaction, and failure logging."""

    def __init__(
        self,
        status: IntervalsSyncStatus,
        writer: SyncOperationStateWriter,
        redactor: Callable[[str], str],
        logger: logging.Logger,
        utc_now: Callable[[], str],
    ) -> None:
        self._status = status
        self._writer = writer
        self._redactor = redactor
        self._logger = logger
        self._utc_now = utc_now

    def start(self, operation_id: str) -> None:
        started_at = (
            self._status.get("sync_operation_started_at")
            if self._status.get("sync_running") == "1"
            else self._utc_now()
        )
        self._status.set("sync_operation_started_at", started_at or self._utc_now())
        self._writer.write(
            operation_id,
            "running",
            "fetching",
            10,
            "Intervals.icu-Daten werden gelesen…",
        )

    def storing(self, operation_id: str) -> None:
        self._writer.write(
            operation_id,
            "running",
            "storing",
            75,
            "Lokale Trainingsdaten werden aktualisiert…",
        )

    def redacted_error(self, error: str) -> str:
        return self._redactor(error)

    def complete(self, operation_id: str) -> None:
        self._writer.write(
            operation_id,
            "completed",
            "complete",
            100,
            "Intervals.icu-Synchronisierung abgeschlossen.",
        )
        self._status.set("sync_operation_finished_at", self._utc_now())

    def failure(self, operation_id: str, reason: str, exc: Exception) -> None:
        if isinstance(exc, AppError) and exc.reason == "chat_cancelled":
            self._writer.write(
                operation_id,
                "cancelled",
                "cancelled",
                100,
                "Intervals.icu-Synchronisierung abgebrochen.",
            )
            self._status.set("sync_operation_finished_at", self._utc_now())
            return
        self._status.set("last_sync_error", self._redactor(str(exc))[:1000])
        self._writer.write(
            operation_id,
            "error",
            "error",
            100,
            "Intervals.icu-Synchronisierung fehlgeschlagen.",
            str(exc),
        )
        self._status.set("sync_operation_finished_at", self._utc_now())
        self._logger.error(
            "Intervals.icu synchronization failed",
            extra={
                "event": "sync_failed",
                "context": {
                    "reason": reason,
                    "last_success": self._status.get("last_sync_at"),
                },
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )


class IntervalsSyncRuntime:
    """Own lock/gate/observation coordination and wait-for-existing behavior."""

    def __init__(
        self,
        lock: Any,
        observer: SyncOperationObserver,
        provider_resync_gate: ProviderResyncGate,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 120.0,
    ) -> None:
        self._lock = lock
        self._observer = observer
        self._provider_resync_gate = provider_resync_gate
        self._monotonic = monotonic
        self._wait_seconds = wait_seconds

    @contextmanager
    def operation(self, reason: str, operation_id: str | None) -> Iterator[Any]:
        with (
            self._observer.observe("intervals", "activities", reason, operation_id) as scope,
            self._provider_resync_gate.operation(),
        ):
            yield scope

    def running(self, status: IntervalsSyncStatus) -> bool:
        return self._lock.locked() or status.get("sync_running") == "1"

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()

    def wait_for_existing(
        self,
        status: IntervalsSyncStatus,
        followup: PerformanceRefreshFollowupService,
        journal: IntervalsSyncJournal,
        all_sync_days: int,
        wait_for_performance: bool,
        cancel_event: threading.Event | None,
        previous_sync_at: str | None,
    ) -> dict[str, Any]:
        deadline = self._monotonic() + self._wait_seconds
        while self._monotonic() < deadline:
            self._raise_if_cancelled(cancel_event)
            remaining = max(0.05, min(1.0, deadline - self._monotonic()))
            if not self._lock.acquire(timeout=remaining):
                continue
            try:
                current_sync_at = status.get("last_sync_at")
                if current_sync_at and current_sync_at != previous_sync_at:
                    return self._completed_wait_result(
                        status,
                        followup,
                        all_sync_days,
                        current_sync_at,
                        wait_for_performance,
                        cancel_event,
                    )
                last_error = journal.redacted_error(
                    status.get("last_sync_error") or ""
                )
                detail = f" {last_error[:300]}" if last_error else ""
                raise AppError(
                    503,
                    "Die laufende Intervals.icu-Synchronisierung konnte nicht "
                    f"abgeschlossen werden.{detail}",
                    reason="provider_refresh_failed",
                )
            finally:
                self._lock.release()
        raise AppError(
            503,
            "Die laufende Intervals.icu-Synchronisierung ist noch nicht "
            "abgeschlossen. Bitte später erneut versuchen.",
            reason="provider_busy",
        )

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")

    @staticmethod
    def _completed_wait_result(
        status: IntervalsSyncStatus,
        followup: PerformanceRefreshFollowupService,
        all_sync_days: int,
        current_sync_at: str,
        wait_for_performance: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        try:
            completed_activity_days = int(status.get("last_sync_activity_days") or 0)
        except (TypeError, ValueError):
            completed_activity_days = 0
        if wait_for_performance:
            followup.wait(cancel_event=cancel_event)
        result: dict[str, Any] = {
            "status": "ok",
            "waited_for_existing": True,
            "synced_at": current_sync_at,
        }
        if completed_activity_days > 0 or completed_activity_days == all_sync_days:
            result["activity_days"] = completed_activity_days
        return result


class IntervalsSyncService:
    """Own the complete read-only Intervals synchronization lifecycle."""

    def __init__(
        self,
        config: Config,
        workflow: IntervalsSyncWorkflow,
        performance_followup_service: PerformanceRefreshFollowupService,
        status: IntervalsSyncStatus,
        journal: IntervalsSyncJournal,
        runtime: IntervalsSyncRuntime,
    ) -> None:
        self._config = config
        self._workflow = workflow
        self._performance_followup_service = performance_followup_service
        self._status = status
        self._journal = journal
        self._runtime = runtime

    def running(self) -> bool:
        return self._runtime.running(self._status)

    def sync(
        self,
        reason: str = "manual",
        activity_days: int | None = None,
        operation_id: str | None = None,
        end_date: date | None = None,
        wait_for_existing: bool = False,
        wait_for_performance: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        with self._runtime.operation(reason, operation_id) as scope:
            result = self._sync_inner(
                reason,
                activity_days,
                operation_id or scope.operation_id,
                end_date,
                wait_for_existing,
                wait_for_performance,
                cancel_event,
            )
            scope.result = result
            return result

    def _sync_inner(
        self,
        reason: str,
        activity_days: int | None,
        operation_id: str,
        end_date: date | None,
        wait_for_existing: bool,
        wait_for_performance: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        if activity_days is None:
            activity_days = self._workflow.sync_period()
        self._raise_if_cancelled(cancel_event)
        if not self._runtime.acquire():
            if not wait_for_existing:
                return {"status": "already_running"}
            return self._runtime.wait_for_existing(
                self._status,
                self._performance_followup_service,
                self._journal,
                self._workflow.all_sync_days,
                wait_for_performance,
                cancel_event,
                self._status.get("last_sync_at"),
            )

        resolved_operation_id = operation_id
        try:
            resolved_operation_id = (
                self._status.get("sync_operation_id")
                if self._status.get("sync_running") == "1"
                else None
            ) or operation_id
            return self._execute(
                reason,
                activity_days,
                resolved_operation_id,
                end_date,
                wait_for_performance,
                cancel_event,
            )
        except Exception as exc:
            self._journal.failure(resolved_operation_id, reason, exc)
            raise
        finally:
            self._finish()

    def _execute(
        self,
        reason: str,
        activity_days: int,
        operation_id: str,
        end_date: date | None,
        wait_for_performance: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        self._journal.start(operation_id)
        self._status.set("sync_running", "1")
        self._status.set("sync_status", "Intervals.icu: Synchronisierung läuft…")
        result = self._workflow.synchronize(
            reason,
            activity_days,
            end_date,
            cancel_event,
            operation_id,
            self._journal,
        )
        self._journal.complete(operation_id)
        performance_job = (
            self._performance_followup_service.enqueue_after_sync(reason)
            if end_date is None
            else None
        )
        if performance_job:
            result["performance_refresh_job_id"] = performance_job["id"]
        if wait_for_performance:
            self._performance_followup_service.wait(
                performance_job["id"] if performance_job else None,
                cancel_event=cancel_event,
            )
        return result

    def _finish(self) -> None:
        try:
            self._status.set("sync_running", "0")
            self._status.set("sync_status", "")
        finally:
            self._runtime.release()

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
