"""Execute durable provider synchronization jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from backend.athlete.local_date import iso_date_prefix
from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.providers.descriptors import (
    CALENDAR_ID,
    GARMIN_ID,
    INTERVALS_ID,
    WEATHER_ID,
)
from backend.sync.competitions import CompetitionSyncService
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.garmin import GarminFixtureLoader
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminSyncService,
    refresh_morning_battery_after_sync,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.intervals import IntervalsSyncService
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import (
    JobValidationError,
    decode_job_payload,
    normalize_sync_job_request,
)
from backend.sync.observation import SyncOperationObserver
from backend.sync.performance import PerformanceRefreshService
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import ProviderJobOwner
from backend.sync.queue import SyncJobQueueService
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.state import SyncStateRepository
from backend.sync.weather import WeatherSyncService

_LOGGER = logging.getLogger(__name__)

# Consecutive chunks without any fetched record (2 x 90 days) end a backfill.
EMPTY_BACKFILL_CHUNK_LIMIT = 2
# Pause between backfill chunks so queued foreground work claims the writer first.
BACKFILL_CONTINUATION_DELAY = timedelta(seconds=15)


class HistoricalSyncJobOwner:
    """Own sync windows and the continuation of historical backfills."""

    def __init__(
        self,
        *,
        sync_state_repository: SyncStateRepository,
        queue_service: SyncJobQueueService,
        local_now: Callable[[], datetime],
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        sync_chunk_days: int,
        sync_earliest_date: date,
    ) -> None:
        self._sync_state_repository = sync_state_repository
        self._queue_service = queue_service
        self._local_now = local_now
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._sync_chunk_days = sync_chunk_days
        self._sync_earliest_date = sync_earliest_date

    def sync_period(self, provider: str) -> int:
        return self._sync_state_repository.sync_period(
            provider, self._sync_period_defaults, self._all_sync_days
        )

    def window(
        self,
        payload: dict[str, Any],
        job_type: str,
        sync_days: Callable[[], int],
    ) -> tuple[int, date | None]:
        """Return the job's (days, end_date) window.

        ``sync_days`` is the provider's default window for this job type. It is
        resolved only when the payload does not carry its own value, so the
        state read happens exactly when it did before the provider was injected.
        """
        if job_type != "historical_backfill":
            days = int(payload.get("days") or sync_days())
            end_date = payload.get("end_date")
            return days, date.fromisoformat(
                iso_date_prefix(str(end_date))
            ) if end_date else None
        days = max(
            1,
            min(
                int(payload.get("days") or self._sync_chunk_days),
                self._sync_chunk_days,
            ),
        )
        refresh_days = sync_days()
        default_end = self._local_now().date() - timedelta(days=refresh_days)
        end_date = date.fromisoformat(
            iso_date_prefix(str(payload.get("end_date") or default_end.isoformat()))
        )
        # Never fetch below the configured floor.
        days = max(1, min(days, (end_date - self._sync_earliest_date).days + 1))
        return days, end_date

    def below_floor(
        self, provider: str, job_type: str, historical_end: date | None
    ) -> dict[str, Any] | None:
        """End a backfill whose window lies wholly below the floor without a fetch."""
        if (
            job_type != "historical_backfill"
            or historical_end is None
            or historical_end >= self._sync_earliest_date
        ):
            return None
        # The cursor at the floor keeps a restart from resuming the walk.
        self._sync_state_repository.update_cursor(
            provider, "historical", self._sync_earliest_date.isoformat()
        )
        return {"status": "ok", "window_records": 0, "historical_next_end": None}

    def add_next_end(
        self,
        provider: str,
        payload: Mapping[str, Any],
        result: dict[str, Any],
        historical_end: date | None,
        days: int,
    ) -> None:
        """Declare the next chunk, or end the chain at the floor or after empty history."""
        if historical_end is None:
            return
        next_end = historical_end - timedelta(days=days)
        result["historical_next_end"] = (
            next_end.isoformat() if next_end >= self._sync_earliest_date else None
        )
        # Only a complete chunk that fetched nothing counts as empty; a result
        # without a count is treated as non-empty.
        empty = result.get("status") == "ok" and result.get("window_records") == 0
        empty_chunks = int(payload.get("empty_chunks") or 0) + 1 if empty else 0
        if empty_chunks >= EMPTY_BACKFILL_CHUNK_LIMIT:
            # The cursor at the floor keeps a restart from resuming the walk.
            result["historical_next_end"] = None
            self._sync_state_repository.update_cursor(
                provider, "historical", self._sync_earliest_date.isoformat()
            )
        result["historical_empty_chunks"] = empty_chunks

    def queue_next(
        self, job: dict[str, Any], result: Any, fallback_status: str
    ) -> None:
        # A partial chunk stops the chain: providers advance their historical
        # cursor only for complete windows, so continuing would skip the gap.
        if not (
            job.get("type") == "historical_backfill"
            and isinstance(result, dict)
            and result.get("historical_next_end")
            and fallback_status == "completed"
        ):
            return
        next_end = result["historical_next_end"]
        # A chunk that ran again (a retry or a restart) may already have queued
        # its continuation; queuing again would start a second chain.
        if self._queue_service.backfill_continued(
            job["provider"], next_end, str(job.get("created_at") or "")
        ):
            return
        payload: dict[str, Any] = {
            "days": self._sync_chunk_days,
            "end_date": next_end,
            "reason": "fortgesetzter historischer Backfill",
        }
        if result.get("historical_empty_chunks"):
            payload["empty_chunks"] = result["historical_empty_chunks"]
        self._queue_service.enqueue(
            job["provider"],
            "historical_backfill",
            payload,
            requested_by="backfill",
            available_at=(self._local_now() + BACKFILL_CONTINUATION_DELAY).isoformat(),
        )


class IntervalsSyncJobOwner:
    """Own Intervals job routing, competitions, and their provider gate."""

    def __init__(
        self,
        *,
        historical_sync: HistoricalSyncJobOwner,
        intervals_sync_service: IntervalsSyncService,
        performance_refresh_service: PerformanceRefreshService,
        selected_workout_sync_service: SelectedWorkoutSyncService,
        competition_sync_service: CompetitionSyncService,
        sync_operation_observer: SyncOperationObserver,
        intervals_resync_gate: ProviderResyncGate,
        activity_detail_service: Any = None,
    ) -> None:
        self._historical_sync = historical_sync
        self._intervals_sync_service = intervals_sync_service
        self._performance_refresh_service = performance_refresh_service
        self._selected_workout_sync_service = selected_workout_sync_service
        self._competition_sync_service = competition_sync_service
        self._sync_operation_observer = sync_operation_observer
        self._intervals_resync_gate = intervals_resync_gate
        self._activity_detail_service = activity_detail_service

    def execute_specific(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        job_type: str,
    ) -> dict[str, Any] | None:
        if job_type == "activity_details":
            if self._activity_detail_service is None:
                raise AppError(503, "Aktivitätsdetails sind nicht verfügbar.")
            with self._intervals_resync_gate.operation():
                return self._activity_detail_service.refresh(payload["activity_id"])
        if job_type == "performance_refresh":
            return self._performance_refresh_service.refresh()
        if job_type == "competition_push":
            return self._sync_competitions(
                reason,
                push_local=True,
                operation_id=job["id"],
                approval_manifest=payload.get("approval_manifest"),
            )
        if job_type == "plan_push":
            selected_payload = {"entries": payload.get("entries")}
            if payload.get("repair"):
                selected_payload["repair"] = True
            return self._selected_workout_sync_service.sync(selected_payload)
        return None

    def execute_sync(
        self, job: Mapping[str, Any], payload: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        days, historical_end = self._historical_sync.window(
            payload,
            str(job.get("type") or ""),
            lambda: self._historical_sync.sync_period(INTERVALS_ID),
        )
        floor_result = self._historical_sync.below_floor(
            INTERVALS_ID, str(job.get("type") or ""), historical_end
        )
        if floor_result is not None:
            return floor_result
        sync_kwargs: dict[str, Any] = {
            "reason": reason,
            "activity_days": days,
            "operation_id": job["id"],
        }
        if historical_end is not None:
            sync_kwargs["end_date"] = historical_end
        elif payload.get("automatic") is True:
            sync_kwargs["automatic"] = True
        result = self._intervals_sync_service.sync(**sync_kwargs)
        if str(job.get("type") or "") == "historical_backfill":
            self._historical_sync.add_next_end(
                INTERVALS_ID, payload, result, historical_end, days
            )
            # Backfill chunks only add history; refreshes own competitions.
            return result
        if result.get("status") == "already_running":
            return result
        if self._activity_detail_service is not None:
            try:
                result["detail_prefetch"] = self._activity_detail_service.prefetch_new(
                    self._intervals_resync_gate.operation
                )
            except Exception:  # noqa: BLE001 - prefetch is best effort; the window is synced
                result["detail_prefetch"] = {"status": "error"}
        try:
            result["competitions"] = self._sync_competitions(
                reason, push_local=False, operation_id=job["id"]
            )
        except Exception:  # noqa: BLE001 - competition failure remains a partial refresh
            # The job stays partial so the competitions section can be retried;
            # the flag records whether the Intervals window itself was complete.
            result["window_complete"] = result.get("status") == "ok"
            result["status"] = "partial"
            result["competitions"] = {"status": "error"}
        return result

    def _sync_competitions(
        self,
        reason: str,
        *,
        push_local: bool,
        operation_id: str,
        approval_manifest: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        with (
            self._sync_operation_observer.observe(
                INTERVALS_ID, "competitions", reason, operation_id
            ) as scope,
            self._intervals_resync_gate.operation(),
        ):
            sync_arguments = {"reason": reason, "push_local": push_local}
            if approval_manifest is not None:
                sync_arguments["expected_manifest"] = approval_manifest
            result = self._competition_sync_service.sync(**sync_arguments)
            scope.result = result
            return result


class GarminSyncJobOwner:
    """Own Garmin job windows and fixture/morning-follow-up rules."""

    def __init__(
        self,
        *,
        historical_sync: HistoricalSyncJobOwner,
        garmin_sync_service: GarminSyncService,
        morning_body_battery_service: MorningBodyBatteryService,
        garmin_fixture_loader: GarminFixtureLoader,
        all_sync_days: int,
        activity_detail_service: Any = None,
    ) -> None:
        self._historical_sync = historical_sync
        self._garmin_sync_service = garmin_sync_service
        self._morning_body_battery_service = morning_body_battery_service
        self._garmin_fixture_loader = garmin_fixture_loader
        self._all_sync_days = all_sync_days
        self._activity_detail_service = activity_detail_service

    def execute(
        self, job: Mapping[str, Any], payload: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        job_type = str(job.get("type") or "")
        if job_type == "activity_details":
            # One activity, read-only: no window, floor or morning follow-up.
            if self._activity_detail_service is None:
                raise AppError(503, "Aktivitätsdetails sind nicht verfügbar.")
            return self._activity_detail_service.refresh(payload["activity_id"])
        days, historical_end = self._historical_sync.window(
            payload, job_type, lambda: self._sync_days(job_type)
        )
        floor_result = self._historical_sync.below_floor(
            GARMIN_ID, job_type, historical_end
        )
        if floor_result is not None:
            return floor_result
        sync_kwargs: dict[str, Any] = {
            "days": days,
            "operation_id": job["id"],
            "reason": reason,
            "include_recovery": (
                job_type != "historical_backfill" and days != self._all_sync_days
            ),
        }
        if historical_end is not None and self._garmin_fixture_loader.path() is None:
            sync_kwargs["end_date"] = historical_end
        result = self._garmin_sync_service.sync(**sync_kwargs)
        if historical_end is None and days != self._all_sync_days:
            refresh_morning_battery_after_sync(
                result, self._morning_body_battery_service
            )
        if job_type == "historical_backfill":
            self._historical_sync.add_next_end(
                GARMIN_ID, payload, result, historical_end, days
            )
        return result

    def _sync_days(self, job_type: str) -> int:
        """Return the default window: backfills use the automatic refresh span."""
        if job_type == "historical_backfill":
            return GARMIN_AUTOMATIC_SYNC_DAYS
        return self._historical_sync.sync_period(GARMIN_ID)


class CalendarWeatherSyncJobOwner:
    """Own dispatch for the non-athlete calendar and weather providers."""

    def __init__(
        self,
        *,
        external_calendar_sync_service: ExternalCalendarSyncService,
        weather_sync_service: WeatherSyncService,
    ) -> None:
        self._external_calendar_sync_service = external_calendar_sync_service
        self._weather_sync_service = weather_sync_service

    def execute(
        self,
        provider: str,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        if provider == CALENDAR_ID:
            return self._external_calendar_sync_service.sync(
                reason=reason, operation_id=job["id"]
            )
        if provider == WEATHER_ID:
            return self._weather_sync_service.sync(
                reason=reason,
                force=bool(payload.get("force", True)),
                operation_id=job["id"],
            )
        raise AppError(400, "Unbekannter Providerjob.", reason="invalid_job_request")


def _reject_plan_push(job_type: str) -> None:
    """Refuse plan pushes outside the authorized planning workflow."""
    if job_type == "plan_push":
        raise AppError(
            409,
            "Plan-Push-Jobs werden erst durch den autorisierten Planungsworkflow ausgeführt.",
            reason="unsupported_job",
        )


class IntervalsJobAdapter:
    """Route Intervals jobs: nutrition inline, specific job types, then the sync."""

    def __init__(
        self, *, jobs: IntervalsSyncJobOwner, nutrition_sync_service: Any
    ) -> None:
        self._jobs = jobs
        self._nutrition_sync_service = nutrition_sync_service

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        if job_type == "nutrition_sync":
            return self._nutrition_sync(payload)
        specific = self._jobs.execute_specific(job, payload, reason, job_type)
        if specific is not None:
            return specific
        _reject_plan_push(job_type)
        return self._jobs.execute_sync(job, payload, reason)

    def _nutrition_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "approval_manifest" in payload:
            result = self._nutrition_sync_service.sync_approved(
                payload["approval_manifest"]
            )
            incomplete = result.get("pending_dates") or result.get("failed_dates")
            return {
                "status": "partial" if incomplete else "completed",
                "synced_dates": result["synced_dates"],
                "pending_dates": result.get("pending_dates", []),
                "failed_dates": sorted(result.get("failed_dates", {})),
            }
        if "date" in payload:
            result = self._nutrition_sync_service.sync_day(payload["date"])
            return {
                "status": "partial" if result.get("pending") else "completed",
                "date": result["date"],
                "pending": result.get("pending", False),
            }
        result = self._nutrition_sync_service.sync_pending(payload["pending_limit"])
        incomplete = result.get("pending_dates") or result.get("failed_dates")
        return {
            "status": "partial" if incomplete else "completed",
            "synced_dates": result["synced_dates"],
            "pending_dates": result.get("pending_dates", []),
            "failed_dates": sorted(result.get("failed_dates", {})),
        }


class GarminJobAdapter:
    """Refuse plan pushes, then run the Garmin sync owner."""

    def __init__(self, *, jobs: GarminSyncJobOwner) -> None:
        self._jobs = jobs

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        _reject_plan_push(job_type)
        return self._jobs.execute(job, payload, reason)


class WahooSyncJobOwner(Protocol):
    """Runs one Wahoo read synchronization."""

    def sync(
        self,
        days: object = None,
        reason: str = "manual",
        operation_id: str | None = None,
    ) -> dict[str, Any]: ...


class WahooPlanPushOwner(Protocol):
    """Exports the selected library workouts as Wahoo plans."""

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class WahooJobAdapter:
    """Run the explicit Wahoo plan export or the read-only Wahoo sync."""

    def __init__(
        self, *, sync: WahooSyncJobOwner, plan_push: WahooPlanPushOwner | None = None
    ) -> None:
        self._sync = sync
        self._plan_push = plan_push

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        if job_type == "plan_push" and self._plan_push is not None:
            selected_payload = {"entries": payload.get("entries")}
            if payload.get("repair"):
                selected_payload["repair"] = True
            return self._plan_push.sync(selected_payload)
        _reject_plan_push(job_type)
        return self._sync.sync(payload.get("days"), reason, operation_id=job["id"])


class CalendarWeatherJobAdapter:
    """Refuse plan pushes, then run the calendar or weather sync for one provider."""

    def __init__(self, *, jobs: CalendarWeatherSyncJobOwner, provider_id: str) -> None:
        self._jobs = jobs
        self._provider_id = provider_id

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        _reject_plan_push(job_type)
        return self._jobs.execute(self._provider_id, job, payload, reason)


def dispatch_provider_job(
    job_owners: Mapping[str, ProviderJobOwner],
    job: Mapping[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """Run a normalized job through the owner registered for its provider."""
    payload = envelope["payload"]
    provider = envelope["provider"]
    job_type = envelope["type"]
    reason = str(payload.get("reason") or "Persistenter Providerjob")
    owner = job_owners.get(provider)
    if owner is None:
        _reject_plan_push(job_type)
        raise AppError(400, "Unbekannter Providerjob.", reason="invalid_job_request")
    return owner.execute(job, payload, reason, job_type=job_type)


def build_job_owners(
    *,
    intervals_jobs: IntervalsSyncJobOwner,
    nutrition_sync_service: Any,
    garmin_jobs: GarminSyncJobOwner,
    calendar_weather_jobs: CalendarWeatherSyncJobOwner,
) -> dict[str, ProviderJobOwner]:
    """Return the provider-to-owner mapping for the built-in providers."""
    return {
        INTERVALS_ID: IntervalsJobAdapter(
            jobs=intervals_jobs, nutrition_sync_service=nutrition_sync_service
        ),
        GARMIN_ID: GarminJobAdapter(jobs=garmin_jobs),
        CALENDAR_ID: CalendarWeatherJobAdapter(
            jobs=calendar_weather_jobs, provider_id=CALENDAR_ID
        ),
        WEATHER_ID: CalendarWeatherJobAdapter(
            jobs=calendar_weather_jobs, provider_id=WEATHER_ID
        ),
    }


class SyncJobExecutor:
    """Run one claimed job and persist its outcome and any backfill follow-up."""

    def __init__(
        self,
        *,
        historical_sync: HistoricalSyncJobOwner,
        outcome_service: SyncJobOutcomeService,
        all_sync_days: int,
        job_owners: Mapping[str, ProviderJobOwner],
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._job_owners = job_owners
        self._historical_sync = historical_sync
        self._outcome_service = outcome_service
        self._all_sync_days = all_sync_days
        self._registry = registry

    def run(self, job: dict[str, Any]) -> None:
        """Execute a claimed job, recording failures through its outcome owner."""
        try:
            result = self.execute(job)
            fallback_status = self._outcome_service.complete(job["id"], result)
            self._historical_sync.queue_next(job, result, fallback_status)
        except Exception as exc:  # noqa: BLE001 - runner persists every execution failure
            try:
                self._outcome_service.record_failure(job, exc)
            except Exception as secondary:  # noqa: BLE001 - the worker must survive
                _LOGGER.error(
                    "sync job failure could not be recorded",
                    extra={
                        "event": "sync_job_failure_record_failed",
                        "job_id": job.get("id"),
                        "error_class": type(secondary).__name__,
                    },
                )
                try:
                    self._outcome_service.update(
                        job["id"], "failed", error_class=type(exc).__name__
                    )
                except Exception:  # noqa: BLE001 - restart recovery requeues it
                    _LOGGER.error(
                        "sync job could not be marked failed",
                        extra={"event": "sync_job_last_resort_failed"},
                    )

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        """Normalize and dispatch a persisted provider-job envelope."""
        stored_payload = job.get("payload")
        try:
            envelope = normalize_sync_job_request(
                str(job.get("provider") or ""),
                str(job.get("type") or ""),
                dict(stored_payload)
                if isinstance(stored_payload, dict)
                else decode_job_payload(stored_payload),
                all_sync_days=self._all_sync_days,
                registry=self._registry,
            )
        except JobValidationError as exc:
            raise AppError(400, str(exc), reason="invalid_job_request") from exc
        return dispatch_provider_job(self._job_owners, job, envelope)
