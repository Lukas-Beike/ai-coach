"""Every (provider, job type) reaches its provider service through the real wiring.

The user and the Coach start sync jobs over ``POST /api/sync/jobs``. This matrix
drives each pair the registry declares through the real built-in runtime
bindings, the real job queue and store, payload normalization, the real executor
and the real outcome service, on a temporary SQLite database. Fakes stand in only
for the provider services that talk to the outside world (their HTTP clients sit
below them). Nothing here mocks the configured check or invents a provider.

The expected pairs are listed by hand and compared with the registry, so a new
descriptor or job type fails here until the matrix covers it. No network, no real
``.env``, no data directory and no provider account.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast
from unittest import mock

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.nutrition.contracts import nutrition_approval_item
from backend.providers.descriptors import (
    CALENDAR_ID,
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
    WEATHER_ID,
)
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_assembly import (
    CalendarWeatherJobDependencies,
    GarminJobDependencies,
    HistoricalSyncDependencies,
    IntervalsJobDependencies,
    SyncJobExecutionAssembly,
    SyncJobStateDependencies,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_runtime_assembly import (
    ProviderRuntimeDependencies,
    WahooRuntimeDependencies,
    build_provider_runtime,
    builtin_bindings,
)
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
JOBS = "/api/sync/jobs"
UNIT = "11111111-1111-4111-8111-111111111111"
ENTRIES = [{"library_workout_id": UNIT, "expected_payload_hash": "a" * 64}]
COMPETITIONS = [{"type": "competition", "id": "race-1", "sha256": "b" * 64}]
NUTRITION = [nutrition_approval_item({"date": "2026-11-08", "total_kcal": 2000})]
BACKFILL_END = "2026-10-01"
OK = {"status": "ok", "window_records": 3}

# The pairs the UI, the Coach and the schedulers send, written out by hand:
# plan_push from the calendar buttons and Coach cards, activity_details from the
# activity view, refresh from the sync buttons, schedulers and Coach, nutrition and
# competition pushes from Coach cards, and the backfills from startup.
EXPECTED_PAIRS: Final = frozenset(
    {
        (INTERVALS_ID, "plan_push"),
        (INTERVALS_ID, "competition_push"),
        (INTERVALS_ID, "nutrition_sync"),
        (GARMIN_ID, "refresh"),
        (GARMIN_ID, "historical_backfill"),
        (GARMIN_ID, "wellness_backfill"),
        (GARMIN_ID, "rating_backfill"),
        (GARMIN_ID, "stream_backfill"),
        (GARMIN_ID, "activity_details"),
        (GARMIN_ID, "plan_push"),
        (WAHOO_ID, "refresh"),
        (WAHOO_ID, "plan_push"),
        (WAHOO_ID, "stream_backfill"),
        (WEATHER_ID, "refresh"),
        (CALENDAR_ID, "refresh"),
    }
)
# Providers whose descriptor carries a not_configured_message.
CONFIGURABLE: Final = frozenset({INTERVALS_ID, GARMIN_ID, WAHOO_ID})

# (provider, type) -> request payload and the provider service call it must reach.
CASES: Final[dict[tuple[str, str], tuple[dict[str, Any], str]]] = {
    (INTERVALS_ID, "plan_push"): ({"entries": ENTRIES}, "intervals.plan"),
    (INTERVALS_ID, "competition_push"): (
        {"reason": "test", "approval_manifest": COMPETITIONS},
        "intervals.competitions",
    ),
    (INTERVALS_ID, "nutrition_sync"): (
        {"approval_manifest": NUTRITION},
        "intervals.nutrition",
    ),
    (GARMIN_ID, "refresh"): ({"days": 7, "reason": "manual"}, "garmin.sync"),
    (GARMIN_ID, "historical_backfill"): (
        {"days": 30, "end_date": BACKFILL_END},
        "garmin.sync",
    ),
    (GARMIN_ID, "wellness_backfill"): (
        {"days": 30, "end_date": BACKFILL_END},
        "garmin.wellness",
    ),
    (GARMIN_ID, "rating_backfill"): ({"end_date": BACKFILL_END}, "garmin.ratings"),
    (GARMIN_ID, "stream_backfill"): ({"end_date": BACKFILL_END}, "garmin.streams"),
    (GARMIN_ID, "activity_details"): ({"activity_id": "act-1"}, "garmin.details"),
    (GARMIN_ID, "plan_push"): ({"entries": ENTRIES}, "garmin.plan"),
    (WAHOO_ID, "refresh"): ({"days": 7, "reason": "manual"}, "wahoo.sync"),
    (WAHOO_ID, "plan_push"): ({"entries": ENTRIES}, "wahoo.plan"),
    (WAHOO_ID, "stream_backfill"): ({"end_date": BACKFILL_END}, "wahoo.streams"),
    (WEATHER_ID, "refresh"): ({"force": True, "reason": "manual"}, "weather.sync"),
    (CALENDAR_ID, "refresh"): ({"reason": "manual"}, "calendar.sync"),
}


def registry_pairs() -> frozenset[tuple[str, str]]:
    return frozenset(
        (descriptor.provider_id, job_type)
        for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
        for job_type in descriptor.job_types
    )


class _Service:
    """A provider service double: records its calls and returns a fixed result."""

    def __init__(self, name: str, calls: list[str], result: dict[str, Any]) -> None:
        self._name = name
        self._calls = calls
        self._result = result

    def _hit(self) -> dict[str, Any]:
        self._calls.append(self._name)
        return dict(self._result)

    def sync(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._hit()

    def refresh(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._hit()

    def backfill(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._hit()

    def rearm(self) -> None:
        """The Wahoo refresh restarts the stream chain; the double has none."""

    def sync_approved(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {**self._hit(), "synced_dates": []}

    def sync_pending(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {**self._hit(), "synced_dates": []}

    def sync_day(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {**self._hit(), "date": "2026-11-09"}

    def available(self) -> bool:
        return True


class _Connected(_Service):
    """A provider service with a switchable configured state."""

    def __init__(self, name: str, calls: list[str], connected: bool) -> None:
        super().__init__(name, calls, OK)
        self.connected = connected

    def configured(self) -> bool:
        return self.connected

    def running(self) -> bool:
        return False


class _Observer:
    @contextlib.contextmanager
    def observe(self, *args: Any, **kwargs: Any) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(result=None)


class Harness:
    """Real runtime, queue, executor and outcomes over fakes at the provider boundary."""

    def __init__(
        self,
        case: unittest.TestCase,
        *,
        intervals_key: str = "fake-key",
        garmin: bool = True,
        wahoo: bool = True,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        case.addCleanup(temporary.cleanup)
        self.database = DatabaseManager(
            Path(temporary.name) / "matrix.sqlite", sqlite3, row_factory=sqlite3.Row
        )
        case.addCleanup(self.database.close)
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.calls: list[str] = []
        self.garmin = _Connected("garmin.sync", self.calls, garmin)
        self.wahoo = _Connected("wahoo.sync", self.calls, wahoo)
        config: Any = SimpleNamespace(
            intervals_api_key=intervals_key, calendar_ical_url="https://example.invalid"
        )

        def service(name: str, result: dict[str, Any] = OK) -> Any:
            return _Service(name, self.calls, result)

        publisher = mock.Mock(spec=StateEventBuffer)
        wake = threading.Event()
        key_values = KeyValueRepository(NOW.isoformat)
        identifiers = iter(f"job-{index}" for index in range(1, 500))
        self.store = SyncJobStore(
            self.database, NOW.isoformat, lambda: next(identifiers)
        )
        self.queue = SyncJobQueueService(
            self.store,
            publisher,
            MaintenanceGate(),
            wake,
            all_sync_days=-1,
            daily_sync_markers=DailySyncMarkerService(
                self.database, key_values, lambda: NOW
            ),
        )
        outcomes = SyncJobOutcomeService(
            self.store,
            publisher,
            wake,
            lambda text: text,
            logging.getLogger("test.sync_wiring_matrix"),
            lambda: NOW,
            retry_base_seconds=1,
            retry_max_seconds=60,
        )
        state_repository = SyncStateRepository(
            self.database, key_values, SnapshotRepository(), NOW.isoformat
        )
        historical = HistoricalSyncDependencies(
            local_now=lambda: NOW,
            sync_period_defaults={GARMIN_ID: 7, WAHOO_ID: 7},
            all_sync_days=-1,
            sync_chunk_days=30,
            sync_earliest_date=date(2026, 1, 1),
        )
        state = SyncJobStateDependencies(
            sync_state_repository=lambda: state_repository,
            queue_service=lambda: self.queue,
            outcome_service=lambda: outcomes,
        )
        intervals = IntervalsJobDependencies(
            selected_workout_sync_service=lambda: service("intervals.plan"),
            competition_sync_service=lambda: service("intervals.competitions"),
            nutrition_sync_service=lambda: service("intervals.nutrition"),
            operation_observer=lambda: cast(Any, _Observer()),
            resync_gate=ProviderResyncGate("Intervals.icu"),
        )
        no_fixture = mock.Mock()
        no_fixture.path.return_value = None
        garmin_deps = GarminJobDependencies(
            sync_service=lambda: self.garmin,
            morning_body_battery_service=lambda: mock.Mock(),
            fixture_loader=lambda: no_fixture,
            activity_detail_service=lambda: service("garmin.details"),
            strength_push_service=lambda: service("garmin.plan"),
            wellness_history_service=lambda: service("garmin.wellness"),
            rating_backfill_service=lambda: service("garmin.ratings"),
            stream_backfill_service=lambda: service("garmin.streams"),
        )
        calendar_weather = CalendarWeatherJobDependencies(
            calendar_sync_service=lambda: service("calendar.sync"),
            weather_sync_service=lambda: service("weather.sync"),
        )
        dependencies = ProviderRuntimeDependencies(
            config=lambda: config,
            profile=lambda: mock.Mock(),
            database_manager=lambda: self.database,
            key_values=key_values,
            database_lock=threading.RLock(),
            garmin_resync_gate=ProviderResyncGate("Garmin"),
            garmin_automatic_sync_days=7,
            historical=historical,
            state=state,
            intervals=intervals,
            garmin=garmin_deps,
            calendar_weather=calendar_weather,
            wahoo=WahooRuntimeDependencies(
                sync_service=lambda: cast(Any, self.wahoo),
                plan_push_service=lambda: service("wahoo.plan"),
                resync_gate=ProviderResyncGate("Wahoo"),
                stream_backfill_service=lambda: service("wahoo.streams"),
            ),
        )
        self.runtime = build_provider_runtime(
            DEFAULT_PROVIDER_REGISTRY, builtin_bindings(dependencies)
        )
        self.executor = SyncJobExecutionAssembly(
            dependencies=SyncJobExecutionAssembly.Inputs(
                historical=historical,
                state=state,
                intervals=intervals,
                garmin=garmin_deps,
                calendar_weather=calendar_weather,
            ),
            provider_runtime=lambda: self.runtime,
        ).executor()
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            mock.Mock(),
            mock.Mock(),
            lambda: "operation-1",
            {GARMIN_ID: 7, WAHOO_ID: 7},
            -1,
            provider_configured=self.runtime.provider_configured,
        )

    def post(self, provider: str, job_type: str, payload: dict[str, Any]) -> dict:
        status, job = self.endpoint.execute(
            JOBS, {"provider": provider, "type": job_type, "payload": payload}
        )
        assert status == 202
        return job

    def run_next(self) -> dict[str, Any]:
        claimed = self.store.claim()
        assert claimed is not None
        self.executor.run(claimed)
        state = self.queue.state(claimed["id"])
        assert state is not None
        return state

    def stored_jobs(self) -> int:
        with self.database.reader() as db:
            return int(db.execute("SELECT COUNT(*) FROM sync_jobs").fetchone()[0])


class RegistryCoverageTests(unittest.TestCase):
    def test_the_matrix_lists_exactly_the_registry_job_types(self) -> None:
        self.assertEqual(EXPECTED_PAIRS, registry_pairs())
        self.assertEqual(EXPECTED_PAIRS, frozenset(CASES))

    def test_configurable_providers_are_those_with_a_not_configured_message(
        self,
    ) -> None:
        self.assertEqual(
            CONFIGURABLE,
            {
                descriptor.provider_id
                for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
                if descriptor.not_configured_message
            },
        )


class ProviderJobWiringTests(unittest.TestCase):
    def test_every_pair_is_accepted_queued_and_executed_by_its_provider(self) -> None:
        for (provider, job_type), (payload, service) in sorted(CASES.items()):
            with self.subTest(provider=provider, type=job_type):
                harness = Harness(self)

                job = harness.post(provider, job_type, payload)

                self.assertEqual(
                    (provider, job_type, "queued"),
                    (job["provider"], job["type"], job["status"]),
                )
                state = harness.run_next()
                self.assertEqual(job["id"], state["id"])
                self.assertEqual("completed", state["status"], state)
                self.assertIn(service, harness.calls)

    def test_an_unconfigured_provider_gets_409_before_any_job_is_stored(self) -> None:
        for provider, job_type in sorted(EXPECTED_PAIRS):
            if provider not in CONFIGURABLE:
                continue
            with self.subTest(provider=provider, type=job_type):
                harness = Harness(self, intervals_key="", garmin=False, wahoo=False)

                with self.assertRaises(AppError) as caught:
                    harness.post(provider, job_type, CASES[provider, job_type][0])

                self.assertEqual(
                    (409, "not_configured"),
                    (caught.exception.status, caught.exception.reason),
                )
                self.assertEqual(
                    DEFAULT_PROVIDER_REGISTRY.get(provider).not_configured_message,
                    caught.exception.message,
                )
                self.assertEqual(0, harness.stored_jobs())

    def test_providers_without_a_message_are_admitted_when_others_are_not(self) -> None:
        for provider, job_type in sorted(EXPECTED_PAIRS):
            if provider in CONFIGURABLE:
                continue
            with self.subTest(provider=provider, type=job_type):
                harness = Harness(self, intervals_key="", garmin=False, wahoo=False)

                harness.post(provider, job_type, CASES[provider, job_type][0])

                self.assertEqual("completed", harness.run_next()["status"])


class ConfiguredCheckTests(unittest.TestCase):
    """The HTTP layer's configured check is the runtime registry's, per provider."""

    def test_each_message_provider_follows_its_own_configuration(self) -> None:
        for only in sorted(CONFIGURABLE):
            with self.subTest(configured=only):
                harness = Harness(
                    self,
                    intervals_key="fake-key" if only == INTERVALS_ID else "",
                    garmin=only == GARMIN_ID,
                    wahoo=only == WAHOO_ID,
                )

                self.assertEqual(
                    {provider: provider == only for provider in CONFIGURABLE},
                    {
                        provider: harness.runtime.provider_configured(provider)
                        for provider in CONFIGURABLE
                    },
                )

    def test_every_message_descriptor_is_bound_in_the_runtime(self) -> None:
        harness = Harness(self)
        for descriptor in DEFAULT_PROVIDER_REGISTRY.all():
            if descriptor.not_configured_message:
                with self.subTest(provider=descriptor.provider_id):
                    # An unbound provider would raise KeyError here, which the
                    # removed full-resync lookup did for Intervals.icu (#1819).
                    self.assertIsInstance(
                        harness.runtime.provider_configured(descriptor.provider_id),
                        bool,
                    )

    def test_the_composition_root_wires_the_endpoint_to_the_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1] / "server.py"
        tree = ast.parse(root.read_text(encoding="utf-8"))
        wired = [
            keyword.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "HttpSyncServices"
            for keyword in node.keywords
            if keyword.arg == "provider_configured"
        ]
        self.assertEqual(1, len(wired))
        calls = [
            node
            for node in ast.walk(wired[0])
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "provider_configured"
        ]
        self.assertEqual(1, len(calls))
        owner = calls[0].func.value  # type: ignore[attr-defined]
        self.assertEqual(
            "provider_runtime",
            getattr(owner.func, "id", ""),
            "HttpSyncServices must take provider_configured from provider_runtime()",
        )


if __name__ == "__main__":
    unittest.main()
