"""Focused tests for persistent synchronization-job execution."""

from __future__ import annotations

import hashlib
import json
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from provider_runtime_fakes import ACME_ID, FakeJobOwner, acme_descriptor

from backend.errors import AppError
from backend.providers.descriptors import CALENDAR_ID, WEATHER_ID
from backend.sync.executor import (
    CalendarWeatherJobAdapter,
    CalendarWeatherSyncJobOwner,
    GarminJobAdapter,
    GarminSyncJobOwner,
    HistoricalSyncJobOwner,
    IntervalsJobAdapter,
    IntervalsSyncJobOwner,
    SyncJobExecutor,
    build_job_owners,
    dispatch_provider_job,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


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


class MockNutritionSync:
    def __init__(self) -> None:
        self.calls = []

    def sync_day(self, day):
        self.calls.append(("day", day))
        return {"date": day, "pending": False}

    def sync_pending(self, limit):
        self.calls.append(("pending", limit))
        return {"synced_dates": ["2026-09-24"], "pending_dates": [], "failed_dates": {}}

    def sync_approved(self, manifest):
        self.calls.append(("approved", manifest))
        return {
            "synced_dates": [item["date"] for item in manifest],
            "pending_dates": [],
            "failed_dates": {},
        }


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


def build_historical_sync(state: Any, queue: Any) -> HistoricalSyncJobOwner:
    return HistoricalSyncJobOwner(
        sync_state_repository=state,
        queue_service=queue,
        local_now=lambda: datetime(2026, 9, 20, 12, tzinfo=UTC),
        sync_period_defaults={"intervals": 90, "garmin": 30},
        all_sync_days=-1,
        sync_chunk_days=90,
        sync_earliest_date=date(2000, 1, 1),
    )


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
        self.nutrition = MockNutritionSync()
        self.executor = self.make_executor()

    def make_executor(self) -> SyncJobExecutor:
        historical_sync = build_historical_sync(self.state, self.queue)
        return SyncJobExecutor(
            job_owners=build_job_owners(
                nutrition_sync_service=self.nutrition,
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
            {
                "job_owners",
                "historical_sync",
                "outcome_service",
                "all_sync_days",
                "registry",
            },
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
            self.job(
                "intervals",
                "competition_push",
                {"reason": "manual", "approval_manifest": []},
            )
        )
        self.assertEqual(competition, {"status": "ok", "count": 2})
        self.assertEqual(
            self.competitions.calls[-1],
            ((), {"reason": "manual", "push_local": True, "expected_manifest": []}),
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

    def test_dispatches_explicit_nutrition_sync_jobs(self) -> None:
        daily = self.executor.execute(
            self.job("intervals", "nutrition_sync", {"date": "2026-09-24"})
        )
        pending = self.executor.execute(
            self.job("intervals", "nutrition_sync", {"pending_limit": 7})
        )
        self.assertEqual(
            daily, {"status": "completed", "date": "2026-09-24", "pending": False}
        )
        self.assertEqual(
            pending,
            {
                "status": "completed",
                "synced_dates": ["2026-09-24"],
                "pending_dates": [],
                "failed_dates": [],
            },
        )
        self.assertEqual(self.nutrition.calls, [("day", "2026-09-24"), ("pending", 7)])

        approved = [
            {
                "date": "2026-09-24",
                "revision": 2,
                "total_kcal": 1200,
                "total_carbs_g": 120.0,
                "total_protein_g": 60.0,
                "total_fat_g": 40.0,
                "entry_count": 2,
            }
        ]
        approved[0]["sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in approved[0].items() if key != "revision"},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result = self.executor.execute(
            self.job("intervals", "nutrition_sync", {"approval_manifest": approved})
        )
        self.assertEqual(
            result,
            {
                "status": "completed",
                "synced_dates": ["2026-09-24"],
                "pending_dates": [],
                "failed_dates": [],
            },
        )
        self.assertEqual(self.nutrition.calls[-1], ("approved", approved))

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

    def test_garmin_historical_default_starts_after_two_day_refresh_window(
        self,
    ) -> None:
        self.garmin.result = {"status": "ok"}

        self.executor.execute(self.job("garmin", "historical_backfill", {"days": 30}))

        self.assertEqual(self.garmin.calls[-1][1]["end_date"], date(2026, 9, 18))
        self.assertEqual(self.morning.calls, [])

    def test_garmin_refresh_forwards_explicit_catchup_end_date(self) -> None:
        self.executor.execute(
            self.job("garmin", payload={"days": 90, "end_date": "2025-05-29"})
        )
        self.assertEqual(self.garmin.calls[-1][1]["days"], 90)
        self.assertEqual(self.garmin.calls[-1][1]["end_date"], date(2025, 5, 29))
        self.assertTrue(self.garmin.calls[-1][1]["include_recovery"])
        self.assertNotIn("historical_next_end", self.garmin.result)

    def test_garmin_refresh_without_days_resolves_the_garmin_sync_period(self) -> None:
        self.executor.execute(self.job("garmin"))

        self.assertEqual(self.garmin.calls[-1][1]["days"], 30)
        self.assertEqual(self.state.calls[-1][0], "garmin")

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
                        "include_recovery": False,
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


class HistoricalWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.historical = build_historical_sync(
            RecordingStateRepository(), RecordingQueue()
        )

    def test_explicit_days_do_not_resolve_the_provider_default(self) -> None:
        resolved: list[bool] = []

        def sync_days() -> int:
            resolved.append(True)
            return 30

        self.assertEqual(
            self.historical.window({"days": 12}, "refresh", sync_days), (12, None)
        )
        self.assertEqual(resolved, [])
        self.assertEqual(self.historical.window({}, "refresh", sync_days), (30, None))
        self.assertEqual(resolved, [True])

    def test_backfill_uses_the_provider_refresh_span_as_its_end_boundary(self) -> None:
        self.assertEqual(
            self.historical.window({"days": 500}, "historical_backfill", lambda: 2),
            (90, date(2026, 9, 18)),
        )


class ProviderJobAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = {"id": "job-123", "provider": "intervals", "type": "refresh"}

    def test_intervals_nutrition_runs_inline_without_provider_jobs(self) -> None:
        jobs = Mock()
        nutrition = MockNutritionSync()
        adapter = IntervalsJobAdapter(jobs=jobs, nutrition_sync_service=nutrition)

        result = adapter.execute(
            self.job, {"date": "2026-09-24"}, "manual", job_type="nutrition_sync"
        )

        self.assertEqual(
            result, {"status": "completed", "date": "2026-09-24", "pending": False}
        )
        self.assertEqual(nutrition.calls, [("day", "2026-09-24")])
        jobs.execute_specific.assert_not_called()
        jobs.execute_sync.assert_not_called()

    def test_intervals_specific_result_short_circuits_the_sync(self) -> None:
        jobs = Mock()
        jobs.execute_specific.return_value = {"status": "ok"}
        adapter = IntervalsJobAdapter(jobs=jobs, nutrition_sync_service=Mock())

        result = adapter.execute(self.job, {}, "manual", job_type="performance_refresh")

        self.assertEqual(result, {"status": "ok"})
        jobs.execute_sync.assert_not_called()

    def test_intervals_plan_push_is_rejected_before_the_sync(self) -> None:
        jobs = Mock()
        jobs.execute_specific.return_value = None
        adapter = IntervalsJobAdapter(jobs=jobs, nutrition_sync_service=Mock())

        with self.assertRaises(AppError) as raised:
            adapter.execute(self.job, {}, "manual", job_type="plan_push")

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "unsupported_job")
        jobs.execute_sync.assert_not_called()

    def test_intervals_other_types_fall_through_to_the_sync(self) -> None:
        jobs = Mock()
        jobs.execute_specific.return_value = None
        jobs.execute_sync.return_value = {"status": "ok"}
        adapter = IntervalsJobAdapter(jobs=jobs, nutrition_sync_service=Mock())

        result = adapter.execute(self.job, {}, "manual", job_type="refresh")

        self.assertEqual(result, {"status": "ok"})
        jobs.execute_sync.assert_called_once_with(self.job, {}, "manual")

    def test_garmin_plan_push_is_rejected_and_other_types_delegate(self) -> None:
        jobs = Mock()
        jobs.execute.return_value = {"status": "ok"}
        adapter = GarminJobAdapter(jobs=jobs)

        with self.assertRaises(AppError) as raised:
            adapter.execute(self.job, {}, "manual", job_type="plan_push")
        self.assertEqual(raised.exception.status, 409)
        jobs.execute.assert_not_called()

        self.assertEqual(
            adapter.execute(self.job, {"days": 3}, "manual", job_type="refresh"),
            {"status": "ok"},
        )
        jobs.execute.assert_called_once_with(self.job, {"days": 3}, "manual")

    def test_calendar_and_weather_adapters_reject_plan_push_and_pass_their_id(
        self,
    ) -> None:
        jobs = Mock()
        jobs.execute.return_value = {"status": "ok"}
        for provider_id in (CALENDAR_ID, WEATHER_ID):
            adapter = CalendarWeatherJobAdapter(jobs=jobs, provider_id=provider_id)
            with self.assertRaises(AppError) as raised:
                adapter.execute(self.job, {}, "manual", job_type="plan_push")
            self.assertEqual(raised.exception.status, 409)
            adapter.execute(self.job, {"force": False}, "manual", job_type="refresh")
            jobs.execute.assert_called_with(
                provider_id, self.job, {"force": False}, "manual"
            )
        self.assertEqual(jobs.execute.call_count, 2)


class DispatchProviderJobTests(unittest.TestCase):
    def test_unknown_provider_keeps_the_existing_rejection(self) -> None:
        envelope = {"provider": "unknown", "type": "refresh", "payload": {}}

        with self.assertRaises(AppError) as raised:
            dispatch_provider_job({}, {"id": "job-1"}, envelope)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(str(raised.exception), "Unbekannter Providerjob.")
        self.assertEqual(raised.exception.reason, "invalid_job_request")

    def test_unknown_provider_plan_push_keeps_the_planning_rejection(self) -> None:
        envelope = {"provider": "unknown", "type": "plan_push", "payload": {}}

        with self.assertRaises(AppError) as raised:
            dispatch_provider_job({}, {"id": "job-1"}, envelope)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "unsupported_job")

    def test_calendar_weather_owner_rejects_an_unknown_provider_id(self) -> None:
        calendar = Mock()
        weather = Mock()
        owner = CalendarWeatherSyncJobOwner(
            external_calendar_sync_service=calendar,
            weather_sync_service=weather,
        )

        with self.assertRaises(AppError) as raised:
            owner.execute("weathr", {"id": "job-1"}, {}, "manual")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.reason, "invalid_job_request")
        calendar.sync.assert_not_called()
        weather.sync.assert_not_called()


class AcmeMockProviderJobTests(unittest.TestCase):
    """Drive orchestration with a test-only provider that no production code names."""

    def setUp(self) -> None:
        self.owner = FakeJobOwner({"status": "completed", "rows": 3})
        self.job = {"id": "job-acme", "provider": ACME_ID, "type": "refresh"}
        self.envelope = {
            "provider": ACME_ID,
            "type": "refresh",
            "payload": {"reason": "acme sync"},
        }

    def test_dispatch_routes_the_acme_owner_by_provider_id(self) -> None:
        result = dispatch_provider_job({ACME_ID: self.owner}, self.job, self.envelope)

        self.assertEqual(result, {"status": "completed", "rows": 3})
        self.assertEqual(
            self.owner.calls,
            [
                {
                    "job": self.job,
                    "payload": {"reason": "acme sync"},
                    "reason": "acme sync",
                    "job_type": "refresh",
                }
            ],
        )

    def test_executor_accepts_job_owners_by_keyword_and_runs_the_acme_owner(
        self,
    ) -> None:
        executor = SyncJobExecutor(
            job_owners={ACME_ID: self.owner},
            historical_sync=Mock(),
            outcome_service=cast(Any, RecordingOutcomes()),
            all_sync_days=-1,
        )

        with patch(
            "backend.sync.executor.normalize_sync_job_request",
            return_value=self.envelope,
        ) as normalize:
            result = executor.execute(self.job)

        self.assertEqual(result, {"status": "completed", "rows": 3})
        normalize.assert_called_once_with(
            ACME_ID,
            "refresh",
            {},
            all_sync_days=-1,
            registry=DEFAULT_PROVIDER_REGISTRY,
        )
        self.assertEqual(self.owner.calls[0]["job_type"], "refresh")

    def test_injected_registry_normalizes_the_acme_job_and_default_rejects_it(
        self,
    ) -> None:
        registry = ProviderRegistry(
            (*DEFAULT_PROVIDER_REGISTRY.all(), acme_descriptor())
        )
        job = {
            "id": "job-acme",
            "provider": ACME_ID,
            "type": "refresh",
            "payload": {"reason": "acme sync"},
        }
        injected_owner = FakeJobOwner({"status": "completed", "rows": 3})
        injected = SyncJobExecutor(
            job_owners={ACME_ID: injected_owner},
            historical_sync=Mock(),
            outcome_service=cast(Any, RecordingOutcomes()),
            all_sync_days=-1,
            registry=registry,
        )

        self.assertEqual(injected.execute(job), {"status": "completed", "rows": 3})
        self.assertEqual(injected_owner.calls[0]["payload"], {"reason": "acme sync"})

        default_owner = FakeJobOwner()
        default = SyncJobExecutor(
            job_owners={ACME_ID: default_owner},
            historical_sync=Mock(),
            outcome_service=cast(Any, RecordingOutcomes()),
            all_sync_days=-1,
        )
        with self.assertRaises(AppError) as raised:
            default.execute(job)
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.reason, "invalid_job_request")
        self.assertEqual(default_owner.calls, [])

    def test_run_completes_the_acme_job_and_queues_its_declared_follow_up(
        self,
    ) -> None:
        owner = FakeJobOwner(
            {"status": "completed", "historical_next_end": "2026-01-01"}
        )
        outcomes = RecordingOutcomes()
        historical = Mock()
        executor = SyncJobExecutor(
            job_owners={ACME_ID: owner},
            historical_sync=historical,
            outcome_service=cast(Any, outcomes),
            all_sync_days=-1,
        )

        with patch(
            "backend.sync.executor.normalize_sync_job_request",
            return_value=self.envelope,
        ):
            executor.run(self.job)

        expected = {"status": "completed", "historical_next_end": "2026-01-01"}
        self.assertEqual(outcomes.complete_calls, [("job-acme", expected)])
        historical.queue_next.assert_called_once_with(self.job, expected, "completed")
        self.assertEqual(outcomes.failure_calls, [])

    def test_unknown_provider_is_rejected_by_normalization_before_dispatch(
        self,
    ) -> None:
        executor = SyncJobExecutor(
            job_owners={ACME_ID: self.owner},
            historical_sync=Mock(),
            outcome_service=cast(Any, RecordingOutcomes()),
            all_sync_days=-1,
        )

        with self.assertRaises(AppError) as raised:
            executor.execute(self.job)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.reason, "invalid_job_request")
        self.assertEqual(self.owner.calls, [])


if __name__ == "__main__":
    unittest.main()
