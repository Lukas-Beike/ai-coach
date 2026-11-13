"""Execute durable provider synchronization jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final, Protocol

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID
from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.sync.competitions import CompetitionSyncService
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.garmin import GarminFixtureLoader
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminSyncService,
    refresh_morning_battery_after_sync,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.intervals_state import (
    INTERVALS_OUTPUT_FAILED_KEY,
    INTERVALS_OUTPUT_OK_KEY,
)
from backend.sync.job_outcomes import CONTENDED_STATUS, SyncJobOutcomeService
from backend.sync.jobs import (
    BACKFILL_CURSOR_STREAMS,
    BACKFILL_JOB_TYPES,
    STREAM_BACKFILL,
    WELLNESS_BACKFILL,
    JobValidationError,
    decode_job_payload,
    normalize_sync_job_request,
)
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.queue import SyncJobQueueService
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.state import SyncStateRepository
from backend.sync.weather import WeatherSyncService

UNKNOWN_PROVIDER_JOB: Final = "Unbekannter Providerjob."
_LOGGER = logging.getLogger("intervals_coach")

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
        if job_type not in BACKFILL_JOB_TYPES:
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
            job_type not in BACKFILL_JOB_TYPES
            or historical_end is None
            or historical_end >= self._sync_earliest_date
        ):
            return None
        # The cursor at the floor keeps a restart from resuming the walk.
        self._sync_state_repository.update_cursor(
            provider,
            BACKFILL_CURSOR_STREAMS[job_type],
            self._sync_earliest_date.isoformat(),
        )
        return {"status": "ok", "window_records": 0, "historical_next_end": None}

    def add_next_end(
        self,
        provider: str,
        payload: Mapping[str, Any],
        result: dict[str, Any],
        historical_end: date | None,
        days: int,
        job_type: str = "historical_backfill",
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
                provider,
                BACKFILL_CURSOR_STREAMS[job_type],
                self._sync_earliest_date.isoformat(),
            )
        result["historical_empty_chunks"] = empty_chunks

    def queue_next(
        self, job: dict[str, Any], result: Any, fallback_status: str
    ) -> None:
        job_type = str(job.get("type") or "")
        if not backfill_continues(job, result, fallback_status):
            return
        next_end = result["historical_next_end"]
        # A chunk that ran again (a retry or a restart) may already have queued
        # its continuation; queuing again would start a second chain.
        if self._queue_service.backfill_continued(
            job["provider"],
            next_end,
            str(job.get("created_at") or ""),
            job_type,
            str(job.get("id") or ""),
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
            job_type,
            payload,
            requested_by="backfill",
            available_at=(self._local_now() + BACKFILL_CONTINUATION_DELAY).isoformat(),
        )


class IntervalsSyncJobOwner:
    """Own the Intervals.icu output jobs: plan and competition pushes."""

    def __init__(
        self,
        *,
        selected_workout_sync_service: SelectedWorkoutSyncService,
        competition_sync_service: CompetitionSyncService,
        sync_operation_observer: SyncOperationObserver,
        intervals_resync_gate: ProviderResyncGate,
    ) -> None:
        self._selected_workout_sync_service = selected_workout_sync_service
        self._competition_sync_service = competition_sync_service
        self._sync_operation_observer = sync_operation_observer
        self._intervals_resync_gate = intervals_resync_gate

    def execute_specific(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        job_type: str,
    ) -> dict[str, Any] | None:
        if job_type == "competition_push":
            return self._sync_competitions(
                reason,
                operation_id=job["id"],
                approval_manifest=payload.get("approval_manifest"),
            )
        if job_type == "plan_push":
            selected_payload = {"entries": payload.get("entries")}
            if payload.get("repair"):
                selected_payload["repair"] = True
            return self._selected_workout_sync_service.sync(selected_payload)
        return None

    def _sync_competitions(
        self,
        reason: str,
        *,
        operation_id: str,
        approval_manifest: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        with (
            self._sync_operation_observer.observe(
                INTERVALS_ID, "competitions", reason, operation_id
            ) as scope,
            self._intervals_resync_gate.operation(),
        ):
            sync_arguments: dict[str, Any] = {"reason": reason}
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
        wellness_history_service: GarminWellnessBackfill | None = None,
        stream_backfill_service: StreamBackfill | None = None,
    ) -> None:
        self._historical_sync = historical_sync
        self._wellness_history_service = wellness_history_service
        self._stream_backfill_service = stream_backfill_service
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
        if job_type == WELLNESS_BACKFILL:
            return self._wellness_backfill(payload)
        if job_type == STREAM_BACKFILL:
            return run_stream_backfill(self._stream_backfill_service, payload)
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

    def _wellness_backfill(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one insert-only wellness history chunk (no activities, no deletion)."""
        if self._wellness_history_service is None:
            raise AppError(503, "Der Wellness-Backfill ist nicht verfügbar.")
        if not self._wellness_history_service.available():
            # Fixture mode: no remote read, no cursor move, no continuation.
            return {"status": "ok", "reason": "not_configured", "window_records": 0}
        days, end = self._historical_sync.window(
            payload, WELLNESS_BACKFILL, lambda: GARMIN_AUTOMATIC_SYNC_DAYS
        )
        floor_result = self._historical_sync.below_floor(
            GARMIN_ID, WELLNESS_BACKFILL, end
        )
        if floor_result is not None:
            return floor_result
        assert end is not None  # window() always ends a backfill chunk
        result = self._wellness_history_service.backfill(days, end)
        self._historical_sync.add_next_end(
            GARMIN_ID, payload, result, end, days, WELLNESS_BACKFILL
        )
        return result

    def _sync_days(self, job_type: str) -> int:
        """Return the default window: backfills use the automatic refresh span."""
        if job_type == "historical_backfill":
            return GARMIN_AUTOMATIC_SYNC_DAYS
        return self._historical_sync.sync_period(GARMIN_ID)


class GarminWellnessBackfill(Protocol):
    """Backfills one window of Garmin wellness history."""

    def available(self) -> bool: ...

    def backfill(self, days: int, end: date) -> dict[str, Any]: ...


class EndDateBackfill(Protocol):
    """Backfills one batch of past activities, newest first, up to an end day."""

    def available(self) -> bool: ...

    def backfill(self, end: date | None) -> dict[str, Any]: ...


StreamBackfill = EndDateBackfill


def run_end_date_backfill(
    service: EndDateBackfill | None, payload: Mapping[str, Any], unavailable: str
) -> dict[str, Any]:
    """Run one batch; the chain keeps its cursor and continuation itself."""
    if service is None:
        raise AppError(503, unavailable)
    if not service.available():
        # Fixture mode: no remote read, no cursor move, no continuation.
        return {"status": "ok", "reason": "not_configured", "window_records": 0}
    end_date = payload.get("end_date")
    end = date.fromisoformat(iso_date_prefix(str(end_date))) if end_date else None
    return service.backfill(end)


def run_stream_backfill(
    service: StreamBackfill | None, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Run one stream backfill batch (newest first)."""
    return run_end_date_backfill(
        service, payload, "Der Stream-Backfill ist nicht verfügbar."
    )


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
        raise AppError(400, UNKNOWN_PROVIDER_JOB, reason="invalid_job_request")


def _reject_plan_push(job_type: str) -> None:
    """Refuse plan pushes outside the authorized planning workflow."""
    if job_type == "plan_push":
        raise AppError(
            409,
            "Plan-Push-Jobs werden erst durch den autorisierten Planungsworkflow ausgeführt.",
            reason="unsupported_job",
        )


# Reasons of a provider failure that carries no upstream status (no response).
_PROVIDER_FAILURE_REASONS = frozenset({"provider_network_error", "provider_http_error"})


def _provider_failure(error: Exception) -> bool:
    """Whether an exception is the provider's answer or silence, not a local fault."""
    return isinstance(error, AppError) and (
        error.upstream_status is not None or error.reason in _PROVIDER_FAILURE_REASONS
    )


def _output_stamp(job_type: str, result: dict[str, Any]) -> str | None:
    """The stamp key an output result earns, None when nothing reached Intervals.icu.

    A skipped entry, an already synced one, a conflict with local edits and a
    contended run are local outcomes; only a synced entry, a completed
    competition run or a synced nutrition day proves the connection.
    """
    if job_type == "plan_push":
        entries = [item.get("status") for item in result.get("results") or []]
        if "synced" in entries:
            return INTERVALS_OUTPUT_OK_KEY
        return INTERVALS_OUTPUT_FAILED_KEY if "error" in entries else None
    if job_type == "competition_push":
        return INTERVALS_OUTPUT_OK_KEY if result.get("status") == "ok" else None
    if result.get("synced_dates") or ("date" in result and not result.get("pending")):
        return INTERVALS_OUTPUT_OK_KEY
    # failed_dates also holds local errors (changed approval, busy writer), so a
    # nutrition failure is stamped only from a provider exception, not from here.
    return None


class IntervalsJobAdapter:
    """Route Intervals jobs: nutrition inline, then the plan and competition pushes.

    A job that reached Intervals.icu leaves the stamp of its outcome through
    ``record_output``; the connection chip reads it after a reload.
    """

    def __init__(
        self,
        *,
        jobs: IntervalsSyncJobOwner,
        nutrition_sync_service: Any,
        record_output: Callable[[str], None] = lambda _key: None,
    ) -> None:
        self._jobs = jobs
        self._nutrition_sync_service = nutrition_sync_service
        self._record_output = record_output

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        try:
            result = self._run(job, payload, reason, job_type)
        except Exception as error:
            if _provider_failure(error):
                self._stamp(INTERVALS_OUTPUT_FAILED_KEY)
            raise
        if key := _output_stamp(job_type, result):
            self._stamp(key)
        return result

    def _stamp(self, key: str) -> None:
        """A stamp that cannot be written never changes the job's outcome."""
        try:
            self._record_output(key)
        except Exception:  # noqa: BLE001 - the push already happened
            _LOGGER.warning(
                "Intervals.icu output stamp not stored",
                extra={"event": "intervals_output_stamp_failed"},
            )

    def _run(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        job_type: str,
    ) -> dict[str, Any]:
        if job_type == "nutrition_sync":
            return self._nutrition_sync(payload)
        specific = self._jobs.execute_specific(job, payload, reason, job_type)
        if specific is None:
            raise AppError(400, UNKNOWN_PROVIDER_JOB, reason="invalid_job_request")
        return specific

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


class GarminStrengthPushOwner(Protocol):
    """Pushes the selected strength planned units to Garmin."""

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def remove_past(self) -> int: ...


class GarminJobAdapter:
    """Run the explicit strength-workout push or the Garmin sync owner.

    A finished refresh also removes the app's Garmin workouts of past days (#2185).
    """

    def __init__(
        self,
        *,
        jobs: GarminSyncJobOwner,
        plan_push: GarminStrengthPushOwner | None = None,
    ) -> None:
        self._jobs = jobs
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
        result = self._jobs.execute(job, payload, reason)
        if job_type == "refresh" and self._plan_push is not None:
            self._plan_push.remove_past()
        return result


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


class WahooStreamBackfill(StreamBackfill, Protocol):
    """The stream backfill plus the restart of its chain for a mapper replay."""

    def rearm(self) -> None: ...


class WahooJobAdapter:
    """Run the explicit Wahoo plan export, the stream backfill or the read-only sync.

    A finished refresh restarts the stream chain once per FIT mapper version, so the
    paced backfill downloads the files of sessions an older mapper stored (#1936).
    """

    def __init__(
        self,
        *,
        sync: WahooSyncJobOwner,
        plan_push: WahooPlanPushOwner | None = None,
        stream_backfill: WahooStreamBackfill | None = None,
    ) -> None:
        self._sync = sync
        self._plan_push = plan_push
        self._stream_backfill = stream_backfill

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
        if job_type == STREAM_BACKFILL:
            return run_stream_backfill(self._stream_backfill, payload)
        _reject_plan_push(job_type)
        result = self._sync.sync(payload.get("days"), reason, operation_id=job["id"])
        if self._stream_backfill is not None:
            self._stream_backfill.rearm()
        return result


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


class ProviderJobOwner(Protocol):
    """Executes the provider's queued sync jobs."""

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        """Run one queued job and return its outcome."""


class PerJobOwner:
    """Resolve a provider owner for each job, so it reads the live configuration.

    Owners copy the runtime configuration when they are built, and the worker
    keeps its executor for its lifetime. Building per job lets credentials saved
    or removed in the app apply to the next job without a restart.
    """

    def __init__(self, build: Callable[[], ProviderJobOwner]) -> None:
        self._build = build

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        return self._build().execute(job, payload, reason, job_type=job_type)


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
        raise AppError(400, UNKNOWN_PROVIDER_JOB, reason="invalid_job_request")
    return owner.execute(job, payload, reason, job_type=job_type)


# Job types the Intervals.icu ingest queued before it was removed (#1728). A
# persisted one is retired unrun: it is neither executed nor offered for retry.
INTERVALS_INGEST_JOB_TYPES = frozenset(
    {"refresh", "performance_refresh", "activity_details", "historical_backfill"}
)
INGEST_REMOVED_REASON = "intervals_ingest_removed"


def is_retired_intervals_ingest_job(job: Mapping[str, Any]) -> bool:
    """Return whether a persisted job is an obsolete Intervals.icu ingest job."""
    return (
        str(job.get("provider") or "") == INTERVALS_ID
        and str(job.get("type") or "") in INTERVALS_INGEST_JOB_TYPES
    )


def backfill_continues(
    job: Mapping[str, Any], result: Any, fallback_status: str
) -> bool:
    """Return whether a finished backfill chunk hands over to a next chunk.

    A partial chunk stops the chain: providers advance their historical cursor
    only for complete windows, so continuing would skip the gap.
    """
    return bool(
        str(job.get("type") or "") in BACKFILL_JOB_TYPES
        and isinstance(result, dict)
        and result.get("historical_next_end")
        and fallback_status == "completed"
    )


class SyncJobExecutor:
    """Run one claimed job and persist its outcome and any backfill follow-up.

    A backfill chunk that hands over to a next chunk skips the completion hook;
    the chunk that ends the chain runs it once for the whole walk.
    """

    def __init__(
        self,
        *,
        historical_sync: HistoricalSyncJobOwner,
        outcome_service: SyncJobOutcomeService,
        all_sync_days: int,
        job_owners: Mapping[str, ProviderJobOwner],
        after_job: Callable[[Mapping[str, Any]], None] = lambda _job: None,
    ) -> None:
        self._job_owners = job_owners
        # Runs with each completed job: refreshes derived local values (card M6).
        self._after_job = after_job
        self._historical_sync = historical_sync
        self._outcome_service = outcome_service
        self._all_sync_days = all_sync_days

    def run(self, job: dict[str, Any]) -> None:
        """Execute a claimed job, recording failures through its outcome owner."""
        try:
            if is_retired_intervals_ingest_job(job):
                self._outcome_service.complete(
                    job["id"], {"status": "skipped", "reason": INGEST_REMOVED_REASON}
                )
                return
            result = self.execute(job)
            fallback_status = self._outcome_service.complete(job["id"], result, job=job)
            if fallback_status == CONTENDED_STATUS:
                # The provider was busy: the job is requeued, not finished.
                return
            self._historical_sync.queue_next(job, result, fallback_status)
            chain_continues = backfill_continues(job, result, fallback_status)
        except Exception as exc:  # noqa: BLE001 - runner persists every execution failure
            try:
                self._outcome_service.record_failure(job, exc)
            except Exception as secondary:  # noqa: BLE001 - the worker must survive
                _LOGGER.error(
                    "sync job failure could not be recorded",
                    extra={
                        "event": "sync_job_failure_record_failed",
                        "context": {
                            "job_id": job.get("id"),
                            "error_class": type(secondary).__name__,
                        },
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
        else:
            if not chain_continues:
                self._run_after_job(job)

    def _run_after_job(self, job: Mapping[str, Any]) -> None:
        """Run the completion hook; its failure never changes the job outcome."""
        try:
            self._after_job(job)
        except Exception as exc:  # noqa: BLE001 - the worker must survive
            _LOGGER.error(
                "sync job completion hook failed",
                extra={
                    "event": "sync_job_after_job_failed",
                    "context": {"error_class": type(exc).__name__},
                },
            )

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        """Normalize and dispatch a persisted provider-job envelope."""
        stored_payload = job.get("payload")
        try:
            payload = (
                dict(stored_payload)
                if isinstance(stored_payload, dict)
                else decode_job_payload(stored_payload)
            )
            if str(job.get("type") or "") == "plan_push":
                payload = _unsettled_plan_entries(payload, job.get("settled_item_keys"))
            envelope = normalize_sync_job_request(
                str(job.get("provider") or ""),
                str(job.get("type") or ""),
                payload,
                all_sync_days=self._all_sync_days,
            )
        except JobValidationError as exc:
            raise AppError(400, str(exc), reason="invalid_job_request") from exc
        return dispatch_provider_job(self._job_owners, job, envelope)


def _unsettled_plan_entries(payload: dict[str, Any], settled: Any) -> dict[str, Any]:
    """Drop plan entries a previous run of the same job already completed."""
    entries = payload.get("entries")
    keys = {str(key) for key in settled or ()}
    if not keys or not isinstance(entries, list):
        return payload
    remaining = [
        entry
        for entry in entries
        if not (
            isinstance(entry, dict)
            and str(entry.get("library_workout_id") or "") in keys
        )
    ]
    return {**payload, "entries": remaining} if remaining else payload


def chained_after_job(
    *hooks: Callable[[Mapping[str, Any]], None],
) -> Callable[[Mapping[str, Any]], None]:
    """Return one completion hook that runs each hook in order.

    A failing hook is logged and never skips the hooks after it.
    """

    def after_job(job: Mapping[str, Any]) -> None:
        for hook in hooks:
            try:
                hook(job)
            except Exception as exc:  # noqa: BLE001 - the worker must survive
                _LOGGER.error(
                    "sync job completion hook failed",
                    extra={
                        "event": "sync_job_after_job_failed",
                        "context": {"error_class": type(exc).__name__},
                    },
                )

    return after_job
