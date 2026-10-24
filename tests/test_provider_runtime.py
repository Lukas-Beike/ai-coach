"""Validation and accessor tests for the provider runtime registry."""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any

from provider_runtime_fakes import (
    ACME_AREA,
    ACME_ID,
    FakeJobOwner,
    FakeSchedulePolicy,
    acme_descriptor,
    acme_freshness_source,
    fake_binding,
)

from backend.errors import AppError
from backend.providers.descriptors import (
    DEFAULT_PROVIDER_DESCRIPTORS,
    ProviderDescriptor,
    SchedulePolicy,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.provider_runtime import (
    FreshnessSource,
    ProviderJobOwner,
    ProviderRuntimeBinding,
    ProviderRuntimeRegistry,
    ProviderSchedulePolicy,
)

BETA_ID = "beta-mock"


class _CountingFactory[V]:
    """Returns a fixed value and counts how often the factory ran."""

    def __init__(self, value: V) -> None:
        self._value = value
        self.calls = 0

    def __call__(self) -> V:
        self.calls += 1
        return self._value


class _FakeResync:
    def configured(self) -> bool:
        return True

    def not_configured_error(self) -> AppError:
        return AppError(503, "not configured", reason="not_configured")

    def run(self, operation_id: str, observer: Any) -> dict[str, Any]:
        return {"operation_id": operation_id}


class _FakeSynchronousRefresh:
    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: Any,
    ) -> dict[str, Any]:
        return {"provider": provider}


def _resync_descriptor() -> ProviderDescriptor:
    return dataclasses.replace(
        acme_descriptor(),
        resync_keys=(
            "acme_full_resync_running",
            "acme_full_resync_status",
            "acme_full_resync_at",
            "acme_full_resync_error",
        ),
    )


def _beta_descriptor() -> ProviderDescriptor:
    return dataclasses.replace(
        acme_descriptor(),
        provider_id=BETA_ID,
        default_sync_days=None,
        schedule=SchedulePolicy(daily_rank=50, startup_rank=200, daily_marker=False),
        coach_rank=None,
    )


def _build(
    bindings: Iterable[ProviderRuntimeBinding],
    descriptors: tuple[ProviderDescriptor, ...] | None = None,
) -> ProviderRuntimeRegistry:
    static = ProviderRegistry(
        (*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor(), _beta_descriptor())
        if descriptors is None
        else descriptors
    )
    return ProviderRuntimeRegistry(static, bindings)


def _binding(
    provider_id: str,
    *,
    freshness: Mapping[str, FreshnessSource] | None = None,
    full_resync: Callable[[], Any] | None = None,
    gate: ProviderResyncGate | None = None,
) -> ProviderRuntimeBinding:
    job_owner = FakeJobOwner()
    return ProviderRuntimeBinding(
        provider_id=provider_id,
        job_owner=lambda: job_owner,
        configured=lambda: True,
        gate=gate,
        freshness=(
            {ACME_AREA: acme_freshness_source()} if freshness is None else freshness
        ),
        full_resync=full_resync,
    )


class ProviderRuntimeValidationTests(unittest.TestCase):
    def test_binding_without_descriptor_is_rejected_without_leaking_its_id(
        self,
    ) -> None:
        with self.assertRaises(ValueError) as raised:
            _build([fake_binding("unknown-mock")], descriptors=(acme_descriptor(),))
        self.assertEqual(
            "provider runtime binding has no descriptor", str(raised.exception)
        )
        self.assertNotIn("unknown-mock", str(raised.exception))

    def test_duplicate_binding_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate provider runtime binding"):
            _build([fake_binding(), fake_binding()])

    def test_freshness_sources_must_match_descriptor_area_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "freshness sources must match"):
            _build([fake_binding(freshness={})])
        with self.assertRaisesRegex(ValueError, "freshness sources must match"):
            _build(
                [
                    fake_binding(
                        freshness={
                            ACME_AREA: acme_freshness_source(),
                            "extra": acme_freshness_source(),
                        }
                    )
                ]
            )

    def test_full_resync_requires_descriptor_resync_keys(self) -> None:
        binding = _binding(
            ACME_ID,
            full_resync=_FakeResync,
            gate=ProviderResyncGate(ACME_ID),
        )
        with self.assertRaisesRegex(ValueError, "requires descriptor resync keys"):
            _build([binding])

    def test_resync_keys_require_full_resync_handler(self) -> None:
        binding = _binding(ACME_ID)
        with self.assertRaisesRegex(ValueError, "require a full resync handler"):
            _build([binding], descriptors=(_resync_descriptor(),))

    def test_full_resync_requires_gate(self) -> None:
        binding = _binding(ACME_ID, full_resync=_FakeResync)
        with self.assertRaisesRegex(ValueError, "requires a provider gate"):
            _build([binding], descriptors=(_resync_descriptor(),))

    def test_valid_full_resync_binding_is_accepted(self) -> None:
        binding = _binding(
            ACME_ID,
            full_resync=_FakeResync,
            gate=ProviderResyncGate(ACME_ID),
        )
        registry = _build([binding], descriptors=(_resync_descriptor(),))
        self.assertIs(binding, registry.binding(ACME_ID))


class ProviderRuntimeAccessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = _CountingFactory(FakeJobOwner())
        self.acme_policy = _CountingFactory(FakeSchedulePolicy())
        self.beta_policy = _CountingFactory(FakeSchedulePolicy())
        self.acme = ProviderRuntimeBinding(
            provider_id=ACME_ID,
            job_owner=self.owner,
            configured=lambda: True,
            schedule=self.acme_policy,
            freshness={ACME_AREA: acme_freshness_source()},
        )
        self.beta = ProviderRuntimeBinding(
            provider_id=BETA_ID,
            job_owner=lambda: FakeJobOwner(),
            configured=lambda: True,
            schedule=self.beta_policy,
            freshness={ACME_AREA: acme_freshness_source()},
        )
        self.registry = _build([self.beta, self.acme])

    def test_static_registry_and_binding_lookup(self) -> None:
        self.assertEqual(
            ("intervals", "garmin", "weather", "calendar", "wahoo", ACME_ID, BETA_ID),
            self.registry.static.ids(),
        )
        self.assertIs(self.acme, self.registry.binding(ACME_ID))
        with self.assertRaises(KeyError):
            self.registry.binding("intervals")

    def test_unbound_providers_are_absent_from_every_mapping(self) -> None:
        self.assertNotIn("intervals", self.registry.job_owners())
        self.assertNotIn("intervals", self.registry.schedule_policies()["daily"])
        self.assertNotIn("intervals", self.registry.freshness_sources())
        self.assertNotIn("intervals", self.registry.resync_handlers())
        self.assertNotIn("intervals", self.registry.synchronous_refreshes())
        self.assertNotIn("intervals", self.registry.running_probes())

    def test_job_owners_are_built_lazily_once_in_registry_order(self) -> None:
        self.assertEqual(0, self.owner.calls)
        owners = self.registry.job_owners()
        self.assertEqual(1, self.owner.calls)
        self.assertEqual((ACME_ID, BETA_ID), tuple(owners))
        self.assertIsInstance(owners[ACME_ID], FakeJobOwner)
        self.registry.job_owners()
        self.assertEqual(1, self.owner.calls)

    def test_job_owner_protocol_is_satisfied_by_fake(self) -> None:
        owner: ProviderJobOwner = FakeJobOwner()
        result = owner.execute({"id": "job-1"}, {}, "manual", job_type="refresh")
        self.assertEqual({"status": "completed"}, result)

    def test_schedule_policies_follow_daily_and_startup_order(self) -> None:
        policies = self.registry.schedule_policies()
        self.assertEqual(("beta-mock", ACME_ID), tuple(policies["daily"]))
        self.assertEqual((ACME_ID, BETA_ID), tuple(policies["startup"]))

    def test_schedule_policy_is_built_once_for_both_orders(self) -> None:
        policies = self.registry.schedule_policies()
        self.registry.schedule_policies()
        self.assertEqual(1, self.acme_policy.calls)
        self.assertIs(policies["daily"][ACME_ID], policies["startup"][ACME_ID])
        self.assertIsInstance(policies["daily"][ACME_ID], FakeSchedulePolicy)

    def test_bound_provider_without_schedule_factory_is_absent(self) -> None:
        unscheduled = ProviderRuntimeBinding(
            provider_id=ACME_ID,
            job_owner=lambda: FakeJobOwner(),
            configured=lambda: True,
            freshness={ACME_AREA: acme_freshness_source()},
        )
        registry = _build([unscheduled])
        self.assertEqual({}, dict(registry.schedule_policies()["daily"]))
        self.assertEqual({}, dict(registry.schedule_policies()["startup"]))

    def test_schedule_policy_protocol_is_satisfied_by_fake(self) -> None:
        policy: ProviderSchedulePolicy = FakeSchedulePolicy(blocked=True)
        self.assertTrue(policy.blocked())
        self.assertTrue(policy.configured())
        self.assertEqual(
            {"days": 14, "reason": "daily", "trigger": "daily"},
            policy.refresh_payload("daily", "daily"),
        )

    def test_freshness_sources_are_read_only_per_provider(self) -> None:
        sources = self.registry.freshness_sources()
        self.assertEqual((ACME_ID, BETA_ID), tuple(sources))
        self.assertIs(sources[ACME_ID][ACME_AREA], self.acme.freshness[ACME_AREA])
        with self.assertRaises(TypeError):
            sources[ACME_ID]["other"] = acme_freshness_source()  # type: ignore[index]

    def test_resync_handlers_and_synchronous_refreshes_are_optional(self) -> None:
        gate = ProviderResyncGate(ACME_ID)
        resync = _CountingFactory(_FakeResync())
        refresh = _CountingFactory(_FakeSynchronousRefresh())
        bound = ProviderRuntimeBinding(
            provider_id=ACME_ID,
            job_owner=lambda: FakeJobOwner(),
            configured=lambda: True,
            gate=gate,
            freshness={ACME_AREA: acme_freshness_source()},
            full_resync=resync,
            synchronous_refresh=refresh,
        )
        registry = _build([bound], descriptors=(_resync_descriptor(),))
        self.assertEqual(0, resync.calls)
        handlers = registry.resync_handlers()
        self.assertEqual((ACME_ID,), tuple(handlers))
        self.assertIs(handlers[ACME_ID], registry.resync_handlers()[ACME_ID])
        self.assertEqual(1, resync.calls)
        self.assertIsInstance(handlers[ACME_ID], _FakeResync)
        self.assertEqual((ACME_ID,), tuple(registry.synchronous_refreshes()))
        self.assertEqual(1, refresh.calls)
        self.assertEqual({}, dict(self.registry.resync_handlers()))
        self.assertEqual({}, dict(self.registry.synchronous_refreshes()))

    def test_running_probes_are_returned_for_bound_probes_only(self) -> None:
        probe = _CountingFactory(True)
        probed = ProviderRuntimeBinding(
            provider_id=ACME_ID,
            job_owner=lambda: FakeJobOwner(),
            configured=lambda: True,
            freshness={ACME_AREA: acme_freshness_source()},
            running_probe=probe,
        )
        registry = _build([probed, self.beta])
        probes = registry.running_probes()
        self.assertEqual((ACME_ID,), tuple(probes))
        self.assertTrue(probes[ACME_ID]())
        self.assertEqual({}, dict(self.registry.running_probes()))

    def test_configured_for_job_needs_the_job_type_and_current_configuration(
        self,
    ) -> None:
        configured = {ACME_ID: True, BETA_ID: True}

        def binding(provider_id: str) -> ProviderRuntimeBinding:
            return ProviderRuntimeBinding(
                provider_id=provider_id,
                job_owner=lambda: FakeJobOwner(),
                configured=lambda: configured[provider_id],
                freshness={ACME_AREA: acme_freshness_source()},
            )

        beta = dataclasses.replace(_beta_descriptor(), job_types=frozenset({"plan_push"}))
        registry = _build(
            [binding(BETA_ID), binding(ACME_ID)], (acme_descriptor(), beta)
        )

        self.assertEqual((ACME_ID,), registry.configured_for_job("refresh"))
        self.assertEqual((BETA_ID,), registry.configured_for_job("plan_push"))
        configured[ACME_ID] = False
        self.assertEqual((), registry.configured_for_job("refresh"))
        self.assertEqual((), registry.configured_for_job("activity_details"))

    def test_every_mapping_is_read_only(self) -> None:
        for mapping in (
            self.registry.job_owners(),
            self.registry.schedule_policies(),
            self.registry.freshness_sources(),
            self.registry.resync_handlers(),
            self.registry.synchronous_refreshes(),
            self.registry.running_probes(),
        ):
            with self.subTest(mapping=type(mapping).__name__):
                self.assertIsInstance(mapping, MappingProxyType)
                with self.assertRaises(TypeError):
                    mapping["x"] = None  # type: ignore[index]


class ProviderRuntimeIterableInputTests(unittest.TestCase):
    def test_bindings_may_be_any_iterable(self) -> None:
        bindings = (binding for binding in [fake_binding()])
        registry = _build(bindings, descriptors=(acme_descriptor(),))
        self.assertEqual((ACME_ID,), tuple(registry.job_owners()))

    def test_empty_bindings_yield_empty_mappings(self) -> None:
        registry = _build([], descriptors=(acme_descriptor(),))
        self.assertEqual({}, dict(registry.job_owners()))
        self.assertEqual({}, dict(registry.freshness_sources()))


class RuntimeOrchestrationBindingTests(unittest.TestCase):
    def test_schedule_requires_a_descriptor_rank(self) -> None:
        static = ProviderRegistry(
            (dataclasses.replace(acme_descriptor(), schedule=SchedulePolicy()),)
        )
        with self.assertRaisesRegex(ValueError, "schedule policy requires"):
            ProviderRuntimeRegistry(static, [fake_binding()])

    def test_synchronous_refresh_requires_a_coach_rank(self) -> None:
        static = ProviderRegistry(
            (dataclasses.replace(acme_descriptor(), coach_rank=None),)
        )
        binding = dataclasses.replace(
            fake_binding(), synchronous_refresh=_FakeSynchronousRefresh
        )
        with self.assertRaisesRegex(ValueError, "synchronous refresh requires"):
            ProviderRuntimeRegistry(static, [binding])

    def test_waiting_descriptor_requires_a_synchronous_refresh(self) -> None:
        static = ProviderRegistry(
            (dataclasses.replace(acme_descriptor(), coach_waits_for_completion=True),)
        )
        with self.assertRaisesRegex(ValueError, "waiting requires"):
            ProviderRuntimeRegistry(static, [fake_binding()])
        waiting = dataclasses.replace(
            fake_binding(), synchronous_refresh=_FakeSynchronousRefresh
        )
        registry = ProviderRuntimeRegistry(static, [waiting])
        self.assertIn(ACME_ID, registry.synchronous_refreshes())

    def test_freshness_view_is_copied_at_construction(self) -> None:
        sources = {ACME_AREA: acme_freshness_source()}
        registry = ProviderRuntimeRegistry(
            ProviderRegistry((acme_descriptor(),)),
            [fake_binding(freshness=sources)],
        )
        sources["extra"] = acme_freshness_source()
        self.assertEqual((ACME_AREA,), tuple(registry.freshness_sources()[ACME_ID]))

    def test_factory_may_read_another_accessor_without_deadlock(self) -> None:
        holder: list[ProviderRuntimeRegistry] = []

        def job_owner() -> ProviderJobOwner:
            holder[0].schedule_policies()
            return FakeJobOwner()

        binding = dataclasses.replace(fake_binding(), job_owner=job_owner)
        registry = ProviderRuntimeRegistry(
            ProviderRegistry((acme_descriptor(),)), [binding]
        )
        holder.append(registry)
        self.assertIn(ACME_ID, registry.job_owners())


if __name__ == "__main__":
    unittest.main()
