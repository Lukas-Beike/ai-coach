"""Focused tests for persistent synchronization-job execution."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.errors import AppError
from backend.sync.executor import (
    CalendarWeatherSyncJobOwner,
    GarminSyncJobOwner,
    HistoricalSyncJobOwner,
    IntervalsSyncJobOwner,
    SyncJobExecutor,
    SyncJobProviderDispatcher,
)


class RecordingService:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = {"status": "ok"} if result is None else result
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.during_call = None

    def sync(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self.during_call:
            self.during_call()
        if self.error:
            raise self.error
        return self.result

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


class RecordingStateRepository:
    def __init__(self, period: int = 30) -> None:
        self.period = period
        self.calls: list[tuple[Any, ...]] = []

    def sync_period(self, *args: Any) -> int:
        self.calls.append(args)
        return self.period


class RecordingFixtureLoader:
    def __init__(self, path: Path | None = None) -> None:
        self.fixture_path = path

    def path(self) -> Path | None:
        return self.fixture_path


class RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.scopes: list[SimpleNamespace] = []

    @contextmanager
    def observe(self, *args: Any):
        self.calls.append(args)
        scope = SimpleNamespace(result=None)
        self.scopes.append(scope)
        yield scope


class RecordingGate:
    def __init__(self) -> None:
        self.active = 0
        self.events: list[str] = []

    @contextmanager
    def operation(self):
        self.active += 1
        self.events.append("enter")
        try:
            yield
        finally:
            self.active -= 1
            self.events.append("exit")


class RecordingOutcomes:
    def __init__(self, fallback_status: str = "completed") -> None:
        self.fallback_status = fallback_status
        self.complete_calls: list[tuple[str, Any]] = []
        self.failure_calls: list[tuple[dict[str, Any], BaseException]] = []
        self.complete_error: Exception | None = None

    def complete(self, job_id: str, result: Any) -> str:
        self.complete_calls.append((job_id, result))
        if self.complete_error:
            raise self.complete_error
        return self.fallback_status

    def record_failure(self, job: dict[str, Any], error: BaseException) -> None:
        self.failure_calls.append((job, error))


class RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


class SyncJobExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intervals = RecordingService()
        self.garmin = RecordingService()
        self.calendar = RecordingService()
        self.weather = RecordingService()
        self.performance = RecordingService()
        self.selected = RecordingService()
        self.competitions = RecordingService({"status": "ok", "count": 2})
        self.observer = RecordingObserver()
        self.gate = RecordingGate()
        self.state = RecordingStateRepository()
        self.outcomes = RecordingOutcomes()
        self.queue = RecordingQueue()
        self.morning = RecordingService()
        self.fixture = RecordingFixtureLoader()
        self.executor = self.make_executor()

    def make_executor(self) -> SyncJobExecutor:
        historical_sync = HistoricalSyncJobOwner(
            sync_state_repository=self.state,
            queue_service=self.queue,
            local_now=lambda: datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
            sync_period_defaults={"intervals": 90, "garmin": 30},
            all_sync_days=-1,
            sync_chunk_days=90,
            sync_earliest_date=date(2000, 1, 1),
        )
        return SyncJobExecutor(
            provider_dispatcher=SyncJobProviderDispatcher(
                intervals_jobs=IntervalsSyncJobOwner(
                    historical_sync=historical_sync,
                    intervals_sync_service=self.intervals,
                    performance_refresh_service=self.performance,
                    selected_workout_sync_service=self.selected,
                    competition_sync_service=self.competitions,
                    sync_operation_observer=self.observer,
                    intervals_resync_gate=self.gate,
                ),
                garmin_jobs=GarminSyncJobOwner(
                    historical_sync=historical_sync,
                    garmin_sync_service=self.garmin,
                    morning_body_battery_service=self.morning,
                    garmin_fixture_loader=self.fixture,
                    all_sync_days=-1,
                ),
                calendar_weather_jobs=CalendarWeatherSyncJobOwner(
                    external_calendar_sync_service=self.calendar,
                    weather_sync_service=self.weather,
                ),
            ),
            historical_sync=historical_sync,
            outcome_service=self.outcomes,
            all_sync_days=-1,
        )

    def test_executor_has_concrete_owner_dependencies_not_parameter_bag(self) -> None:
        parameters = signature(SyncJobExecutor).parameters
        self.assertLessEqual(len(parameters), 7)
        self.assertEqual(
            set(parameters),
            {"provider_dispatcher", "historical_sync", "outcome_service", "all_sync_days"},
        )

    @staticmethod
    def job(
        provider: str, job_type: str = "refresh", payload: Any = None
    ) -> dict[str, Any]:
        return {
            "id": "job-123",
            "provider": provider,
            "type": job_type,
            "payload": {} if payload is None else payload,
        }

    def test_dispatches_specific_intervals_jobs_and_preserves_plan_repair(self) -> None:
        performance = self.executor.execute(
            self.job("intervals", "performance_refresh", {"reason": "metrics"})
        )
        self.assertEqual(performance, {"status": "ok"})
        self.assertEqual(self.performance.calls, [((), {})])

        competition = self.executor.execute(
            self.job("intervals", "competition_push", {"reason": "manual"})
        )
        self.assertEqual(competition, {"status": "ok", "count": 2})
        self.assertEqual(
            self.competitions.calls[-1],
            ((), {"reason": "manual", "push_local": True}),
        )

        entry = {
            "library_workout_id": "00000000-0000-0000-0000-000000000001",
            "expected_payload_hash": "a" * 64,
        }
        planned = self.executor.execute(
            self.job("intervals", "plan_push", {"entries": [entry], "repair": True})
        )
        self.assertEqual(planned, {"status": "ok"})
        self.assertEqual(
            self.selected.calls,
            [(({"entries": [entry], "repair": True},), {})],
        )

    def test_intervals_sync_observes_competitions_inside_provider_gate(self) -> None:
        self.competitions.during_call = lambda: self.assertEqual(self.gate.active, 1)

        result = self.executor.execute(
            self.job("intervals", payload={"days": 12, "reason": "manuell"})
        )

        self.assertEqual(result["competitions"], {"status": "ok", "count": 2})
        self.assertEqual(
            self.intervals.calls,
            [
                (
                    (),
                    {
                        "reason": "manuell",
                        "activity_days": 12,
                        "operation_id": "job-123",
                    },
                )
            ],
        )
        self.assertEqual(
            self.observer.calls, [("intervals", "competitions", "manuell", "job-123")]
        )
        self.assertEqual(self.observer.scopes[0].result, {"status": "ok", "count": 2})
        self.assertEqual(self.gate.events, ["enter", "exit"])

    def test_competition_error_makes_intervals_partial_and_busy_skips_competitions(
        self,
    ) -> None:
        self.competitions.error = RuntimeError("fake competition failure")
        result = self.executor.execute(self.job("intervals"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["competitions"], {"status": "error"})

        self.intervals.result = {"status": "already_running"}
        before = len(self.competitions.calls)
        busy_result = self.executor.execute(self.job("intervals"))
        self.assertEqual(busy_result, {"status": "already_running"})
        self.assertEqual(len(self.competitions.calls), before)

    def test_calendar_and_weather_forward_reason_operation_and_force(self) -> None:
        self.executor.execute(self.job("calendar", payload={"reason": "morning"}))
        self.assertEqual(
            self.calendar.calls,
            [((), {"reason": "morning", "operation_id": "job-123"})],
        )
        self.executor.execute(
            self.job("weather", payload={"reason": "manual", "force": False})
        )
        self.assertEqual(
            self.weather.calls,
            [((), {"reason": "manual", "force": False, "operation_id": "job-123"})],
        )

    def test_garmin_historical_default_starts_after_two_day_refresh_window(self) -> None:
        self.garmin.result = {"status": "ok"}

        self.executor.execute(self.job("garmin", "historical_backfill", {"days": 30}))

        self.assertEqual(self.garmin.calls[-1][1]["end_date"], date(2026, 9, 18))
        self.assertEqual(self.morning.calls, [])

    def test_garmin_historical_fixture_omits_end_date_and_never_refreshes_morning(
        self,
    ) -> None:
        self.fixture.fixture_path = Path("fixture.json")
        self.garmin.result = {"status": "partial"}

        result = self.executor.execute(
            self.job(
                "garmin",
                "historical_backfill",
                {"days": 30, "end_date": "2026-06-01"},
            )
        )

        self.assertEqual(result["historical_next_end"], "2026-05-02")
        self.assertEqual(
            self.garmin.calls,
            [
                (
                    (),
                    {
                        "days": 30,
                        "operation_id": "job-123",
                        "reason": "Persistenter Providerjob",
                    },
                )
            ],
        )
        self.assertEqual(self.morning.calls, [])

    def test_garmin_morning_refresh_is_limited_to_regular_success_or_partial(
        self,
    ) -> None:
        self.fixture.fixture_path = Path("fixture.json")
        self.garmin.result = {"status": "partial"}
        self.executor.execute(self.job("garmin", payload={"days": 20}))
        self.assertEqual(len(self.morning.calls), 1)

        self.garmin.result = {"status": "error"}
        self.executor.execute(self.job("garmin", payload={"days": 20}))
        self.assertEqual(len(self.morning.calls), 1)

        self.garmin.result = {"status": "ok"}
        self.executor.execute(self.job("garmin", payload={"days": -1}))
        self.assertEqual(len(self.morning.calls), 1)

    def test_historical_windows_clamp_days_and_respect_earliest_boundary(self) -> None:
        self.intervals.result = {"status": "ok"}
        result = self.executor.execute(
            self.job("intervals", "historical_backfill", {"days": 500})
        )
        self.assertEqual(self.intervals.calls[-1][1]["activity_days"], 90)
        self.assertEqual(self.intervals.calls[-1][1]["end_date"], date(2026, 8, 21))
        self.assertEqual(result["historical_next_end"], "2026-05-23")
        self.assertEqual(self.state.calls[-1][0], "intervals")

        self.intervals.result = {"status": "ok"}
        exact_boundary = self.executor.execute(
            self.job(
                "intervals",
                "historical_backfill",
                {"days": 90, "end_date": "2000-03-31"},
            )
        )
        self.assertEqual(exact_boundary["historical_next_end"], "2000-01-01")

        below_boundary = self.executor.execute(
            self.job(
                "garmin",
                "historical_backfill",
                {"days": 90, "end_date": "2000-03-30"},
            )
        )
        self.assertIsNone(below_boundary["historical_next_end"])

    def test_run_completes_and_queues_next_historical_chunk(self) -> None:
        self.intervals.result = {"status": "ok"}
        job = self.job(
            "intervals",
            "historical_backfill",
            {"days": 90, "end_date": "2026-09-01"},
        )

        self.executor.run(job)

        self.assertEqual(self.outcomes.complete_calls[0][0], "job-123")
        self.assertEqual(
            self.queue.calls,
            [
                (
                    (
                        "intervals",
                        "historical_backfill",
                        {
                            "days": 90,
                            "end_date": "2026-06-03",
                            "reason": "fortgesetzter historischer Backfill",
                        },
                    ),
                    {"requested_by": "backfill"},
                )
            ],
        )
        self.assertEqual(self.outcomes.failure_calls, [])

    def test_run_records_execution_failure_without_reraising(self) -> None:
        failure = RuntimeError("isolated provider failure")
        self.intervals.error = failure
        job = self.job("intervals")

        self.executor.run(job)

        self.assertEqual(self.outcomes.failure_calls, [(job, failure)])
        self.assertEqual(self.outcomes.complete_calls, [])

    def test_run_leaves_already_running_retry_classification_to_outcome_service(
        self,
    ) -> None:
        temporary = AppError(409, "busy", reason="temporary_error")
        self.outcomes.complete_error = temporary
        self.intervals.result = {"status": "already_running"}
        job = self.job("intervals")

        self.executor.run(job)

        self.assertEqual(self.outcomes.failure_calls, [(job, temporary)])
        self.assertEqual(self.queue.calls, [])

    def test_validation_error_keeps_existing_app_error_mapping(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.executor.execute(self.job("intervals", "refresh", {"unknown": True}))
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.reason, "invalid_job_request")


if __name__ == "__main__":
    unittest.main()
