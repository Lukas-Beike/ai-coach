"""Execute durable provider synchronization jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.sync.competitions import CompetitionSyncService
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.garmin import GarminFixtureLoader
from backend.sync.garmin_service import GARMIN_AUTOMATIC_SYNC_DAYS, GarminSyncService
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
from backend.sync.queue import SyncJobQueueService
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.state import SyncStateRepository
from backend.sync.weather import WeatherSyncService


class SyncJobExecutor:
    """Run one claimed job and persist its outcome and any backfill follow-up."""

    def __init__(
        self,
        *,
        intervals_sync_service: IntervalsSyncService,
        garmin_sync_service: GarminSyncService,
        external_calendar_sync_service: ExternalCalendarSyncService,
        weather_sync_service: WeatherSyncService,
        performance_refresh_service: PerformanceRefreshService,
        selected_workout_sync_service: SelectedWorkoutSyncService,
        competition_sync_service: CompetitionSyncService,
        sync_operation_observer: SyncOperationObserver,
        intervals_resync_gate: ProviderResyncGate,
        sync_state_repository: SyncStateRepository,
        outcome_service: SyncJobOutcomeService,
        queue_service: SyncJobQueueService,
        morning_body_battery_service: MorningBodyBatteryService,
        garmin_fixture_loader: GarminFixtureLoader,
        local_now: Callable[[], datetime],
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        sync_chunk_days: int,
        sync_earliest_date: date,
    ) -> None:
        self._intervals_sync_service = intervals_sync_service
        self._garmin_sync_service = garmin_sync_service
        self._external_calendar_sync_service = external_calendar_sync_service
        self._weather_sync_service = weather_sync_service
        self._performance_refresh_service = performance_refresh_service
        self._selected_workout_sync_service = selected_workout_sync_service
        self._competition_sync_service = competition_sync_service
        self._sync_operation_observer = sync_operation_observer
        self._intervals_resync_gate = intervals_resync_gate
        self._sync_state_repository = sync_state_repository
        self._outcome_service = outcome_service
        self._queue_service = queue_service
        self._morning_body_battery_service = morning_body_battery_service
        self._garmin_fixture_loader = garmin_fixture_loader
        self._local_now = local_now
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._sync_chunk_days = sync_chunk_days
        self._sync_earliest_date = sync_earliest_date

    def run(self, job: dict[str, Any]) -> None:
        """Execute a claimed job, recording failures through its outcome owner."""
        try:
            result = self.execute(job)
            fallback_status = self._outcome_service.complete(job["id"], result)
            self._queue_next_historical_backfill(job, result, fallback_status)
        except Exception as exc:  # noqa: BLE001 - runner persists every execution failure
            self._outcome_service.record_failure(job, exc)

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
            )
        except JobValidationError as exc:
            raise AppError(400, str(exc), reason="invalid_job_request") from exc

        payload = envelope["payload"]
        provider = envelope["provider"]
        job_type = envelope["type"]
        reason = str(payload.get("reason") or "Persistenter Providerjob")
        if provider == "intervals":
            specific = self._execute_intervals_specific_job(
                job, payload, reason, job_type
            )
            if specific is not None:
                return specific
        if job_type == "plan_push":
            raise AppError(
                409,
                "Plan-Push-Jobs werden erst durch den autorisierten Planungsworkflow ausgeführt.",
                reason="unsupported_job",
            )
        if provider == "intervals":
            return self._execute_intervals_sync_job(job, payload, reason)
        if provider == "garmin":
            return self._execute_garmin_sync_job(job, payload, reason)
        if provider == "calendar":
            return self._external_calendar_sync_service.sync(
                reason=reason, operation_id=job["id"]
            )
        if provider == "weather":
            return self._weather_sync_service.sync(
                reason=reason,
                force=bool(payload.get("force", True)),
                operation_id=job["id"],
            )
        raise AppError(400, "Unbekannter Providerjob.", reason="invalid_job_request")

    def _historical_sync_window(
        self, payload: dict[str, Any], job_type: str, provider: str
    ) -> tuple[int, date | None]:
        if job_type != "historical_backfill":
            return int(
                payload.get("days")
                or self._sync_state_repository.sync_period(
                    provider, self._sync_period_defaults, self._all_sync_days
                )
            ), None
        days = max(
            1,
            min(
                int(payload.get("days") or self._sync_chunk_days),
                self._sync_chunk_days,
            ),
        )
        refresh_days = (
            GARMIN_AUTOMATIC_SYNC_DAYS
            if provider == "garmin"
            else self._sync_state_repository.sync_period(
                provider, self._sync_period_defaults, self._all_sync_days
            )
        )
        default_end = self._local_now().date() - timedelta(days=refresh_days)
        end_date = date.fromisoformat(
            str(payload.get("end_date") or default_end.isoformat())[:10]
        )
        return days, end_date

    def _historical_next_end(
        self, result: dict[str, Any], historical_end: date | None, days: int
    ) -> None:
        if historical_end is None:
            return
        next_end = historical_end - timedelta(days=days)
        result["historical_next_end"] = (
            next_end.isoformat() if next_end >= self._sync_earliest_date else None
        )

    def _execute_intervals_sync_job(
        self, job: dict[str, Any], payload: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        days, historical_end = self._historical_sync_window(
            payload, str(job.get("type") or ""), "intervals"
        )
        sync_kwargs: dict[str, Any] = {
            "reason": reason,
            "activity_days": days,
            "operation_id": job["id"],
        }
        if historical_end is not None:
            sync_kwargs["end_date"] = historical_end
        result = self._intervals_sync_service.sync(**sync_kwargs)
        self._historical_next_end(result, historical_end, days)
        if result.get("status") == "already_running":
            return result
        try:
            result["competitions"] = self._sync_competitions(
                reason, push_local=False, operation_id=job["id"]
            )
        except Exception:  # noqa: BLE001 - competition failure remains a partial refresh
            result["status"] = "partial"
            result["competitions"] = {"status": "error"}
        return result

    def _execute_garmin_sync_job(
        self, job: dict[str, Any], payload: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        days, historical_end = self._historical_sync_window(
            payload, str(job.get("type") or ""), "garmin"
        )
        sync_kwargs: dict[str, Any] = {
            "days": days,
            "operation_id": job["id"],
            "reason": reason,
        }
        if historical_end is not None and self._garmin_fixture_loader.path() is None:
            sync_kwargs["end_date"] = historical_end
        result = self._garmin_sync_service.sync(**sync_kwargs)
        if (
            historical_end is None
            and days != self._all_sync_days
            and result.get("status") in {"ok", "partial"}
        ):
            self._morning_body_battery_service.refresh()
        self._historical_next_end(result, historical_end, days)
        return result

    def _execute_intervals_specific_job(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
        reason: str,
        job_type: str,
    ) -> dict[str, Any] | None:
        if job_type == "performance_refresh":
            return self._performance_refresh_service.refresh()
        if job_type == "competition_push":
            return self._sync_competitions(
                reason, push_local=True, operation_id=job["id"]
            )
        if job_type == "plan_push":
            selected_payload = {"entries": payload.get("entries")}
            if payload.get("repair"):
                selected_payload["repair"] = True
            return self._selected_workout_sync_service.sync(selected_payload)
        return None

    def _sync_competitions(
        self, reason: str, *, push_local: bool, operation_id: str
    ) -> dict[str, Any]:
        with (
            self._sync_operation_observer.observe(
                "intervals", "competitions", reason, operation_id
            ) as scope,
            self._intervals_resync_gate.operation(),
        ):
            result = self._competition_sync_service.sync(
                reason=reason, push_local=push_local
            )
            scope.result = result
            return result

    def _queue_next_historical_backfill(
        self, job: dict[str, Any], result: Any, fallback_status: str
    ) -> None:
        if not (
            job.get("type") == "historical_backfill"
            and fallback_status == "completed"
            and isinstance(result, dict)
            and result.get("historical_next_end")
        ):
            return
        self._queue_service.enqueue(
            job["provider"],
            "historical_backfill",
            {
                "days": self._sync_chunk_days,
                "end_date": result["historical_next_end"],
                "reason": "fortgesetzter historischer Backfill",
            },
            requested_by="backfill",
        )
