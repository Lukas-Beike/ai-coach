"""Assembly tests for the provider runtime registry and its consumers.

Built-in bindings are checked against the default registry with mocked live
owners. The ``acme-mock`` provider exists only here and proves that the
assemblies consume a runtime registry without provider literals. Its jobs are
routed directly through the registry owners, because executor payload
normalization still reads only the built-in registry.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import unittest
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest import mock

from provider_runtime_fakes import (
    ACME_AREA,
    ACME_ID,
    FakeJobOwner,
    FakeSchedulePolicy,
    acme_descriptor,
    fake_binding,
)

from backend.errors import AppError
from backend.providers.descriptors import (
    CALENDAR_ID,
    DEFAULT_PROVIDER_DESCRIPTORS,
    GARMIN_ID,
    INTERVALS_ID,
    WEATHER_ID,
    SchedulePolicy,
)
from backend.sync.assembly import (
    ProviderRefreshRetryPolicy,
    ProviderSyncAssembly,
    ProviderSyncPersistence,
    ProviderSyncRuntime,
)
from backend.sync.command_assembly import (
    IllnessPauseDependencies,
    SyncCommandAssembly,
    SyncCommandCore,
)
from backend.sync.execution_assembly import SyncJobExecutionAssembly
from backend.sync.executor import dispatch_provider_job
from backend.sync.freshness_sources import DEFAULT_FRESHNESS_SOURCES
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import (
    ProviderRuntimeBinding,
    ProviderRuntimeRegistry,
)
from backend.sync.provider_runtime_assembly import (
    ProviderRuntimeDependencies,
    build_provider_runtime,
    builtin_bindings,
)

BUILTIN_IDS = frozenset({INTERVALS_ID, GARMIN_ID, WEATHER_ID, CALENDAR_ID})
ACME_STATIC = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor()))
ACME_ONLY_STATIC = ProviderRegistry((acme_descriptor(),))
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
ACME_LAST_SYNC = "2026-10-10T08:00:00+00:00"


def _builtin_deps(
    *, intervals_key: str = "", calendar_url: str = ""
) -> ProviderRuntimeDependencies:
    """Stand in for live owners; the bindings only resolve them lazily."""
    config: Any = SimpleNamespace(
        intervals_api_key=intervals_key, calendar_ical_url=calendar_url
    )
    return ProviderRuntimeDependencies(
        config=lambda: config,
        profile=mock.Mock(name="profile"),
        database_manager=mock.Mock(name="database_manager"),
        key_values=mock.Mock(name="key_values"),
        database_lock=mock.Mock(name="database_lock"),
        intervals_sync_lock=mock.Mock(name="intervals_sync_lock"),
        garmin_resync_gate=mock.Mock(name="garmin_resync_gate"),
        garmin_automatic_sync_days=7,
        historical=mock.Mock(
            name="historical", all_sync_days=60, sync_period_defaults={}
        ),
        state=mock.Mock(name="state"),
        intervals=mock.Mock(name="intervals"),
        garmin=mock.Mock(name="garmin"),
        calendar_weather=mock.Mock(name="calendar_weather"),
    )


class _SynchronousRefreshFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: Any,
    ) -> dict[str, Any]:
        self.calls.append((provider, dict(arguments)))
        return {"ok": True, "provider": provider}


class _QueueFake:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str, dict[str, Any], str]] = []

    def enqueue(
        self,
        provider: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        self.enqueued.append((provider, job_type, dict(payload), requested_by))
        return {"id": "job-1"}


class _CursorFake:
    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _DbFake:
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _CursorFake:
        return _CursorFake()


class _DatabaseManagerFake:
    @contextlib.contextmanager
    def unit_of_work(self) -> Iterator[_DbFake]:
        yield _DbFake()


class _KeyValuesFake:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = dict(values)

    def get(self, db: Any, key: str) -> Any:
        return self._values.get(key)


def _acme_binding(
    *,
    owner: FakeJobOwner | None = None,
    policy: FakeSchedulePolicy | None = None,
    refresh: _SynchronousRefreshFake | None = None,
) -> ProviderRuntimeBinding:
    binding = fake_binding(ACME_ID, owner=owner, policy=policy)
    if refresh is None:
        return binding
    return dataclasses.replace(binding, synchronous_refresh=lambda: refresh)


def _command_assembly(
    runtime: Callable[[], ProviderRuntimeRegistry], queue: _QueueFake
) -> SyncCommandAssembly:
    core = SyncCommandCore(
        database_manager=lambda: None,
        queue_service=lambda: queue,
        intervals_sync=lambda: None,
        planned_unit_service=lambda: None,
        competition_service=lambda: None,
        workout_library_sync_state=lambda: None,
        planning_revision=None,
        utc_now=lambda: NOW,
        training_change_limit=10,
        all_sync_days=60,
    )
    illness_pause = IllnessPauseDependencies(
        config=lambda: None,
        intervals_client=lambda: None,
        adaptive_replan_apply=lambda: None,
        adaptive_replan_preview=lambda: None,
        redactor=None,
        today=lambda: None,
    )
    return SyncCommandAssembly(
        core=core, illness_pause=illness_pause, provider_runtime=runtime
    )


class BuiltinBindingTests(unittest.TestCase):
    def test_builtin_bindings_declare_four_providers_in_order(self) -> None:
        bindings = builtin_bindings(_builtin_deps())

        self.assertEqual(
            [binding.provider_id for binding in bindings],
            [INTERVALS_ID, GARMIN_ID, WEATHER_ID, CALENDAR_ID],
        )

    def test_default_registry_accepts_builtin_bindings_with_live_gates(self) -> None:
        deps = _builtin_deps()

        runtime = build_provider_runtime(
            DEFAULT_PROVIDER_REGISTRY, builtin_bindings(deps)
        )

        self.assertIs(runtime.static, DEFAULT_PROVIDER_REGISTRY)
        self.assertIs(runtime.binding(INTERVALS_ID).gate, deps.intervals.resync_gate)
        self.assertIs(runtime.binding(GARMIN_ID).gate, deps.garmin_resync_gate)
        for provider_id in BUILTIN_IDS:
            self.assertEqual(
                dict(runtime.freshness_sources()[provider_id]),
                dict(DEFAULT_FRESHNESS_SOURCES[provider_id]),
            )

    def test_builtin_factories_expose_the_expected_providers(self) -> None:
        runtime = build_provider_runtime(
            DEFAULT_PROVIDER_REGISTRY, builtin_bindings(_builtin_deps())
        )

        self.assertEqual(set(runtime.job_owners()), BUILTIN_IDS)
        self.assertEqual(set(runtime.resync_handlers()), {INTERVALS_ID, GARMIN_ID})
        self.assertEqual(set(runtime.synchronous_refreshes()), {INTERVALS_ID})
        self.assertEqual(set(runtime.running_probes()), {INTERVALS_ID})

    def test_builtin_schedules_follow_registry_order(self) -> None:
        runtime = build_provider_runtime(
            DEFAULT_PROVIDER_REGISTRY,
            builtin_bindings(_builtin_deps(intervals_key="fake", calendar_url="fake")),
        )

        policies = runtime.schedule_policies()

        self.assertEqual(
            list(policies["daily"]),
            [
                pid
                for pid in DEFAULT_PROVIDER_REGISTRY.daily_order()
                if pid in BUILTIN_IDS
            ],
        )
        self.assertEqual(
            list(policies["startup"]),
            [
                pid
                for pid in DEFAULT_PROVIDER_REGISTRY.startup_order()
                if pid in BUILTIN_IDS
            ],
        )


class RegistryValidationTests(unittest.TestCase):
    def test_binding_without_descriptor_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no descriptor"):
            ProviderRuntimeRegistry(ACME_ONLY_STATIC, [fake_binding("unknown-mock")])

    def test_duplicate_binding_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ProviderRuntimeRegistry(
                ACME_ONLY_STATIC, [_acme_binding(), _acme_binding()]
            )

    def test_every_descriptor_requires_a_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "no runtime binding"):
            build_provider_runtime(ACME_ONLY_STATIC, [])

        runtime = build_provider_runtime(ACME_ONLY_STATIC, [_acme_binding()])
        self.assertIs(runtime.static, ACME_ONLY_STATIC)

    def test_freshness_sources_must_match_descriptor_areas(self) -> None:
        with self.assertRaisesRegex(ValueError, "freshness sources"):
            ProviderRuntimeRegistry(ACME_ONLY_STATIC, [fake_binding(freshness={})])

    def test_schedule_requires_a_descriptor_rank(self) -> None:
        unranked = dataclasses.replace(
            acme_descriptor(),
            schedule=SchedulePolicy(
                daily_rank=None, startup_rank=None, daily_marker=False
            ),
        )

        with self.assertRaisesRegex(ValueError, "schedule policy requires"):
            ProviderRuntimeRegistry(ProviderRegistry((unranked,)), [_acme_binding()])


class AcmeAssemblyTests(unittest.TestCase):
    def test_schedule_order_places_acme_by_its_descriptor_rank(self) -> None:
        policy = FakeSchedulePolicy()
        deps = _builtin_deps(intervals_key="fake", calendar_url="fake")
        runtime = ProviderRuntimeRegistry(
            ACME_STATIC,
            (*builtin_bindings(deps), _acme_binding(policy=policy)),
        )

        policies = runtime.schedule_policies()
        bound = BUILTIN_IDS | {ACME_ID}

        self.assertEqual(
            list(policies["daily"]),
            [pid for pid in ACME_STATIC.daily_order() if pid in bound],
        )
        self.assertIs(policies["daily"][ACME_ID], policy)

    def test_queued_refresh_enqueues_through_the_runtime_registry(self) -> None:
        queue = _QueueFake()
        runtime = ProviderRuntimeRegistry(ACME_ONLY_STATIC, [_acme_binding()])
        assembly = _command_assembly(lambda: runtime, queue)

        result = assembly.provider_refresh().start(ACME_ID, {"reason": "r"})

        self.assertEqual(
            result, {"ok": True, "status": "queued", "sync_job_id": "job-1"}
        )
        self.assertEqual(
            queue.enqueued, [(ACME_ID, "refresh", {"reason": "r"}, "coach")]
        )

    def test_waiting_refresh_uses_the_runtime_synchronous_refresh(self) -> None:
        refresh = _SynchronousRefreshFake()
        queue = _QueueFake()
        runtime = ProviderRuntimeRegistry(
            ACME_ONLY_STATIC, [_acme_binding(refresh=refresh)]
        )
        assembly = _command_assembly(lambda: runtime, queue)

        result = assembly.provider_refresh().start(
            ACME_ID, {"_wait_for_completion": True}
        )

        self.assertEqual(result, {"ok": True, "provider": ACME_ID})
        self.assertEqual(refresh.calls[0][0], ACME_ID)
        self.assertEqual(queue.enqueued, [])

    def test_waiting_refresh_rejects_provider_without_synchronous_refresh(self) -> None:
        runtime = ProviderRuntimeRegistry(ACME_ONLY_STATIC, [_acme_binding()])
        assembly = _command_assembly(lambda: runtime, _QueueFake())

        with self.assertRaises(AppError) as ctx:
            assembly.provider_refresh().start(ACME_ID, {"_wait_for_completion": True})

        self.assertEqual(ctx.exception.reason, "invalid_refresh_request")

    def test_freshness_reports_the_runtime_area_from_its_source(self) -> None:
        runtime = ProviderRuntimeRegistry(ACME_ONLY_STATIC, [_acme_binding()])
        # The fakes stand in for typed owners that freshness reads only lazily.
        database: Any = _DatabaseManagerFake()
        key_values: Any = _KeyValuesFake({"acme_last_sync_at": ACME_LAST_SYNC})
        config: Any = SimpleNamespace()
        no_gate: Any = None
        no_event_buffer: Any = None
        assembly = ProviderSyncAssembly(
            dependencies=ProviderSyncAssembly.Inputs(
                persistence=ProviderSyncPersistence(
                    database_manager=lambda: database,
                    key_values=key_values,
                    event_buffer=no_event_buffer,
                ),
                runtime=ProviderSyncRuntime(
                    config=lambda: config,
                    maintenance_gate=no_gate,
                    logger=logging.getLogger("test.provider_runtime"),
                    now=lambda: NOW,
                ),
                retry_policy=ProviderRefreshRetryPolicy(
                    uuid_factory=lambda: "unused",
                    retry_base_seconds=1,
                    retry_max_seconds=2,
                ),
            ),
            provider_runtime=lambda: runtime,
        )

        entries = assembly.freshness_service().current(
            profile={"acme_enabled": True},
            garmin_has_core_error=False,
            garmin_tokenstore_exists=False,
        )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["provider"], ACME_ID)
        self.assertEqual(entry["area"], ACME_AREA)
        self.assertEqual(entry["label"], "Acme mock · Training")
        self.assertTrue(entry["configured"])
        self.assertEqual(entry["last_success_at"], ACME_LAST_SYNC)


class DispatchRoutingTests(unittest.TestCase):
    def test_dispatch_routes_acme_job_through_its_registered_owner(self) -> None:
        owner = FakeJobOwner({"status": "completed", "count": 2})
        runtime = ProviderRuntimeRegistry(
            ACME_ONLY_STATIC, [_acme_binding(owner=owner)]
        )
        job = {"id": 9, "provider": ACME_ID, "type": "refresh", "payload": {}}
        envelope = {
            "provider": ACME_ID,
            "type": "refresh",
            "payload": {"reason": "Coach"},
        }

        result = dispatch_provider_job(runtime.job_owners(), job, envelope)

        self.assertEqual(result, {"status": "completed", "count": 2})
        self.assertEqual(owner.calls[0]["reason"], "Coach")
        self.assertEqual(owner.calls[0]["job_type"], "refresh")

    def test_dispatch_rejects_provider_without_registered_owner(self) -> None:
        runtime = ProviderRuntimeRegistry(ACME_ONLY_STATIC, [_acme_binding()])
        job = {"id": 9, "provider": INTERVALS_ID, "type": "refresh", "payload": {}}
        envelope = {"provider": INTERVALS_ID, "type": "refresh", "payload": {}}

        with self.assertRaises(AppError) as ctx:
            dispatch_provider_job(runtime.job_owners(), job, envelope)

        self.assertEqual(ctx.exception.reason, "invalid_job_request")

    def test_executor_built_from_runtime_routes_to_acme_owner(self) -> None:
        owner = FakeJobOwner({"status": "completed"})
        runtime = ProviderRuntimeRegistry(
            ACME_ONLY_STATIC, [_acme_binding(owner=owner)]
        )
        assembly = SyncJobExecutionAssembly(
            dependencies=SyncJobExecutionAssembly.Inputs(
                historical=mock.Mock(all_sync_days=60),
                state=mock.Mock(),
                intervals=mock.Mock(),
                garmin=mock.Mock(),
                calendar_weather=mock.Mock(),
            ),
            provider_runtime=lambda: runtime,
        )
        job = {
            "id": 7,
            "provider": ACME_ID,
            "type": "refresh",
            "payload": {"reason": "Coach"},
        }

        result = assembly.executor().execute(job)

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(owner.calls[0]["reason"], "Coach")


if __name__ == "__main__":
    unittest.main()
