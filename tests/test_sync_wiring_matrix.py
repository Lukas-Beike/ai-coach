"""Every (provider, job type) reaches its provider service through the real wiring.

The user and the Coach start sync jobs over ``POST /api/sync/jobs``; only the
nutrition export is enqueued by the Coach card directly (#2137). This matrix
drives each pair the registry declares through the real configured checks, the
real job queue and store, payload normalization, the real executor assembly and
the real outcome service, on a temporary SQLite database. Fakes stand in only
for the provider services that talk to the outside world (their HTTP clients sit
below them). Nothing here mocks the configured check or invents a provider.

The expected pairs are listed by hand and compared with the registry, so a new
descriptor or job type fails here until the matrix covers it. No network, no real
``.env``, no data directory and no provider account.
"""

from __future__ import annotations

import ast
import contextlib
import json
import logging
import sqlite3
import threading
import unittest
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast
from unittest import mock

from support import temp_database

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.nutrition.contracts import nutrition_approval_item
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_wiring import (
    build_sync_job_execution,
    configured_for_job,
    provider_configured_checks,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository
from backend.sync.wiring import SyncWindow

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
# Pairs only the Coach card enqueues; the job route rejects them.
COACH_ONLY: Final = frozenset({(INTERVALS_ID, "nutrition_sync")})
# Providers whose descriptor carries a not_configured_message.
CONFIGURABLE: Final = frozenset({INTERVALS_ID, GARMIN_ID, WAHOO_ID})

# Manual route -> provider, request body and the refresh payload it queues.
MANUAL_ROUTES: Final[dict[str, tuple[str, dict[str, Any] | None, dict[str, Any]]]] = {
    "/api/garmin/sync": (GARMIN_ID, {"days": 7}, {"days": 7, "reason": "manual"}),
    "/api/wahoo/sync": (WAHOO_ID, None, {"reason": "manual"}),
    "/api/weather/sync": (WEATHER_ID, None, {"reason": "manuell", "force": True}),
    "/api/external-calendar/sync": (CALENDAR_ID, None, {"reason": "manuell"}),
}

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

    def remove_past(self) -> int:
        """The Garmin refresh removes past pushed workouts; the double has none."""
        return 0

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
        self.database = temp_database(
            case, "matrix.sqlite", row_factory=sqlite3.Row, schema=True
        )
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
        state_repository = SyncStateRepository(self.database, key_values, NOW.isoformat)
        no_fixture = mock.Mock()
        no_fixture.path.return_value = None
        ctx = SimpleNamespace(
            config=lambda: config,
            clock=SimpleNamespace(now=lambda: NOW),
            athlete=SimpleNamespace(profile=lambda: mock.Mock()),
            sync_persistence=SimpleNamespace(state_repository=lambda: state_repository),
            sync_job_queue=SimpleNamespace(
                service=lambda: self.queue, outcome_service=lambda: outcomes
            ),
            provider_sync=SimpleNamespace(
                operation_observer=lambda: cast(Any, _Observer())
            ),
            nutrition=SimpleNamespace(
                intervals_sync_service=lambda: service("intervals.nutrition")
            ),
            morning_body_battery_service=lambda: mock.Mock(),
            garmin=SimpleNamespace(
                sync_service=lambda: self.garmin,
                fixture_loader=lambda: no_fixture,
                activity_detail_service=lambda: service("garmin.details"),
                strength_push_service=lambda: service("garmin.plan"),
                wellness_history_service=lambda: service("garmin.wellness"),
                stream_backfill_service=lambda: service("garmin.streams"),
            ),
            external_calendar=SimpleNamespace(
                sync_service=lambda: service("calendar.sync")
            ),
            wahoo=SimpleNamespace(
                sync_service=lambda: cast(Any, self.wahoo),
                plan_push_service=lambda: service("wahoo.plan"),
                stream_backfill_service=lambda: service("wahoo.streams"),
            ),
        )
        self.configured = provider_configured_checks(cast(Any, ctx))
        self.executor = build_sync_job_execution(
            cast(Any, ctx),
            window=SyncWindow({GARMIN_ID: 7, WAHOO_ID: 7}, -1, 30, date(2026, 1, 1)),
            selected_workout_sync_service=lambda: service("intervals.plan"),
            competition_sync_service=lambda: service("intervals.competitions"),
            weather_sync_service=lambda: service("weather.sync"),
            intervals_resync_gate=ProviderResyncGate("Intervals.icu"),
            after_job=lambda _job: None,
        ).executor()
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            state_repository,
            mock.Mock(),
            lambda: "operation-1",
            {GARMIN_ID: 7, WAHOO_ID: 7},
            -1,
            provider_configured=lambda provider_id: self.configured[provider_id](),
        )

    def start(self, provider: str, job_type: str, payload: dict[str, Any]) -> dict:
        """Start a pair the way its client does: the route, or the Coach card."""
        if (provider, job_type) in COACH_ONLY:
            return self.queue.enqueue(provider, job_type, payload, requested_by="coach")
        return self.post(provider, job_type, payload)

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

                job = harness.start(provider, job_type, payload)

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

    def test_the_configured_guard_normalizes_the_provider_id(self) -> None:
        # The check reads the normalized id (a raw " Garmin " would miss the
        # check table), so case and spaces cannot slip past the 409.
        for spelled, provider in ((" Garmin ", GARMIN_ID), ("WAHOO", WAHOO_ID)):
            with self.subTest(provider=spelled):
                harness = Harness(self, intervals_key="", garmin=False, wahoo=False)

                with self.assertRaises(AppError) as caught:
                    harness.post(spelled, "refresh", CASES[provider, "refresh"][0])

                self.assertEqual(
                    (409, "not_configured"),
                    (caught.exception.status, caught.exception.reason),
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


class ManualRouteWiringTests(unittest.TestCase):
    def test_the_matrix_lists_exactly_the_manual_routes_of_the_table(self) -> None:
        self.assertEqual(
            {(path, provider) for path, (provider, _, _) in MANUAL_ROUTES.items()},
            set(DEFAULT_PROVIDER_REGISTRY.manual_routes()),
        )

    def test_every_manual_route_queues_its_refresh_and_reaches_its_provider(
        self,
    ) -> None:
        for path, (provider, body, queued) in sorted(MANUAL_ROUTES.items()):
            with self.subTest(path=path):
                harness = Harness(self)

                status, job = harness.endpoint.execute(path, body)

                self.assertEqual(202, status)
                self.assertEqual(
                    (provider, "refresh", "queued"),
                    (job["provider"], job["type"], job["status"]),
                )
                with harness.database.reader() as db:
                    stored = db.execute(
                        "SELECT payload FROM sync_jobs WHERE id=?", (job["id"],)
                    ).fetchone()[0]
                self.assertEqual(queued, json.loads(stored))
                self.assertEqual("completed", harness.run_next()["status"])
                self.assertIn(CASES[provider, "refresh"][1], harness.calls)

    def test_an_unconfigured_provider_gets_409_before_its_manual_route_stores_a_job(
        self,
    ) -> None:
        for path, (provider, body, _) in sorted(MANUAL_ROUTES.items()):
            with self.subTest(path=path):
                harness = Harness(self, intervals_key="", garmin=False, wahoo=False)
                message = DEFAULT_PROVIDER_REGISTRY.get(provider).not_configured_message

                if message is None:
                    harness.endpoint.execute(path, body)
                    self.assertEqual(1, harness.stored_jobs())
                    continue
                with self.assertRaises(AppError) as caught:
                    harness.endpoint.execute(path, body)

                self.assertEqual(
                    (409, "not_configured", message),
                    (
                        caught.exception.status,
                        caught.exception.reason,
                        caught.exception.message,
                    ),
                )
                self.assertEqual(0, harness.stored_jobs())


class ConfiguredCheckTests(unittest.TestCase):
    """The HTTP layer's configured check is the provider's live check."""

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
                        provider: harness.configured[provider]()
                        for provider in CONFIGURABLE
                    },
                )

    def test_every_message_provider_has_a_configured_check(self) -> None:
        harness = Harness(self)
        for descriptor in DEFAULT_PROVIDER_REGISTRY.all():
            if descriptor.not_configured_message:
                with self.subTest(provider=descriptor.provider_id):
                    # A provider without a check would raise KeyError here, which
                    # the removed full-resync lookup did for Intervals.icu (#1819).
                    self.assertIsInstance(
                        harness.configured[descriptor.provider_id](),
                        bool,
                    )

    def test_the_composition_root_wires_the_endpoint_to_the_configured_checks(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1] / "server.py"
        tree = ast.parse(root.read_text(encoding="utf-8"))
        wired = [
            keyword.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "build_http_api"
            for keyword in node.keywords
            if keyword.arg == "provider_configured"
        ]
        self.assertEqual(1, len(wired))
        self.assertEqual(
            "PROVIDER_CONFIGURED",
            ast.unparse(wired[0]),
            "build_http_api must take provider_configured from PROVIDER_CONFIGURED",
        )


class ConfiguredForJobTests(unittest.TestCase):
    def test_follows_table_order_job_type_and_live_configuration(self) -> None:
        state = dict.fromkeys(DEFAULT_PROVIDER_REGISTRY.ids(), True)
        checks = {
            provider: (lambda provider=provider: state[provider]) for provider in state
        }

        self.assertEqual(
            (INTERVALS_ID, GARMIN_ID, WAHOO_ID), configured_for_job(checks, "plan_push")
        )
        self.assertEqual((GARMIN_ID,), configured_for_job(checks, "activity_details"))
        state[GARMIN_ID] = False
        self.assertEqual((), configured_for_job(checks, "activity_details"))


class RunningProbeWiringTests(unittest.TestCase):
    def test_the_composition_root_gives_the_public_state_both_probes(self) -> None:
        root = Path(__file__).resolve().parents[1] / "server.py"
        tree = ast.parse(root.read_text(encoding="utf-8"))
        probes = [
            keyword.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "build_public_state"
            for keyword in node.keywords
            if keyword.arg == "running_probes"
        ]
        self.assertEqual(1, len(probes))
        probe = cast(ast.Dict, probes[0])
        self.assertEqual(
            ["GARMIN_ID", "WAHOO_ID"], [ast.unparse(key) for key in probe.keys if key]
        )
        # A Garmin run sets running, like the operation fields it writes (#2706).
        self.assertIn("GARMIN_ASSEMBLY.sync_service().running()", ast.unparse(probe))
        self.assertIn("WAHOO_SYNC.sync_service().running()", ast.unparse(probe))


if __name__ == "__main__":
    unittest.main()
