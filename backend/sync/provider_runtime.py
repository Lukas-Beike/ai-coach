"""Runtime contracts for provider-owned synchronization orchestration.

Providers contribute runtime objects (job owners, schedule policies, freshness
sources, full-resync handlers, synchronous refreshes, running probes) through a
``ProviderRuntimeBinding``. ``ProviderRuntimeRegistry`` checks each binding
against the static descriptor in ``ProviderRegistry`` and exposes the bound
objects in descriptor order.

The module only declares protocols, dataclasses and the validating registry. It
wires nothing and names no provider. Factories are called on first request.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeVar

from backend.errors import AppError
from backend.providers.descriptors import ProviderDescriptor
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_registry import ProviderRegistry

_T = TypeVar("_T")


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


class ProviderSchedulePolicy(Protocol):
    """Decides whether a provider is scheduled and what its refresh payload is."""

    def configured(self) -> bool:
        """Return whether the provider has the settings it needs."""

    def blocked(self) -> bool:
        """Return whether a scheduled refresh must wait."""

    def refresh_payload(
        self, trigger: Literal["daily", "startup"], reason: str
    ) -> dict[str, Any]:
        """Return the job payload for a scheduled refresh."""


@dataclass(frozen=True, slots=True)
class FreshnessInputs:
    """Inputs the freshness fallbacks read.

    ``signals`` carries provider-specific observations that are not stored as
    key-value settings, such as whether a provider's core error is present.
    """

    config: Any
    get_value: Callable[[str], Any]
    profile: Mapping[str, Any]
    signals: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FreshnessSource:
    """Fallback timestamp, fallback error and configured predicate for one area."""

    fallback_at: Callable[[FreshnessInputs], Any]
    fallback_error: Callable[[FreshnessInputs], Any]
    configured: Callable[[FreshnessInputs], bool]


class FullResyncHandler(Protocol):
    """Runs a provider's full resync for one operation."""

    def configured(self) -> bool:
        """Return whether the provider can run a full resync."""

    def not_configured_error(self) -> AppError:
        """Return the error raised when the provider is not configured."""

    def run(self, operation_id: str, observer: SyncOperationObserver) -> dict[str, Any]:
        """Run the full resync and return its result."""


class SynchronousRefresh(Protocol):
    """Performs a refresh inline for a Coach request that waits for completion."""

    def refresh(
        self,
        provider: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        """Run the refresh and return its result."""


@dataclass(frozen=True, slots=True)
class ProviderRuntimeBinding:
    """Runtime objects one provider contributes to synchronization.

    Each factory is called at most once, on the first request for it. A
    provider with ``full_resync`` needs a ``gate`` and descriptor resync keys.
    ``freshness`` keys must equal the descriptor's freshness area names.
    """

    provider_id: str
    job_owner: Callable[[], ProviderJobOwner]
    configured: Callable[[], bool]
    gate: ProviderResyncGate | None = None
    schedule: Callable[[], ProviderSchedulePolicy] | None = None
    freshness: Mapping[str, FreshnessSource] = field(default_factory=dict)
    full_resync: Callable[[], FullResyncHandler] | None = None
    synchronous_refresh: Callable[[], SynchronousRefresh] | None = None
    running_probe: Callable[[], bool] | None = None


def _descriptor_for(
    static: ProviderRegistry, binding: ProviderRuntimeBinding
) -> ProviderDescriptor:
    try:
        return static.get(binding.provider_id)
    except KeyError as exc:
        raise ValueError("provider runtime binding has no descriptor") from exc


def _check_not_duplicate(
    by_id: Mapping[str, ProviderRuntimeBinding], binding: ProviderRuntimeBinding
) -> None:
    if binding.provider_id in by_id:
        raise ValueError("duplicate provider runtime binding")


def _check_freshness_keys(
    descriptor: ProviderDescriptor, binding: ProviderRuntimeBinding
) -> None:
    if set(binding.freshness) != {area.area for area in descriptor.freshness_areas}:
        raise ValueError("freshness sources must match descriptor freshness areas")


def _check_resync(
    descriptor: ProviderDescriptor, binding: ProviderRuntimeBinding
) -> None:
    if binding.full_resync is not None and not descriptor.resync_keys:
        raise ValueError("full resync handler requires descriptor resync keys")
    if binding.full_resync is None and descriptor.resync_keys:
        raise ValueError("descriptor resync keys require a full resync handler")
    if binding.full_resync is not None and binding.gate is None:
        raise ValueError("full resync handler requires a provider gate")


def _check_capabilities(
    descriptor: ProviderDescriptor, binding: ProviderRuntimeBinding
) -> None:
    if binding.schedule is not None and not _has_schedule_rank(descriptor):
        raise ValueError("schedule policy requires a descriptor schedule rank")
    if binding.synchronous_refresh is not None and descriptor.coach_rank is None:
        raise ValueError("synchronous refresh requires a descriptor coach rank")
    if descriptor.coach_waits_for_completion and binding.synchronous_refresh is None:
        raise ValueError("descriptor waiting requires a synchronous refresh")


def _has_schedule_rank(descriptor: ProviderDescriptor) -> bool:
    return (
        descriptor.schedule.daily_rank is not None
        or descriptor.schedule.startup_rank is not None
    )


def _validate_binding(
    static: ProviderRegistry,
    binding: ProviderRuntimeBinding,
    by_id: Mapping[str, ProviderRuntimeBinding],
) -> None:
    """Check one binding against its descriptor, in a fixed order."""
    descriptor = _descriptor_for(static, binding)
    _check_not_duplicate(by_id, binding)
    _check_freshness_keys(descriptor, binding)
    _check_resync(descriptor, binding)
    _check_capabilities(descriptor, binding)


class ProviderRuntimeRegistry:
    """Validated, read-only view of provider runtime bindings.

    Accessors return mappings in static registry order. A provider in the static
    registry without a binding is absent from every mapping.
    """

    def __init__(
        self,
        static: ProviderRegistry,
        bindings: Iterable[ProviderRuntimeBinding],
    ) -> None:
        by_id: dict[str, ProviderRuntimeBinding] = {}
        for binding in bindings:
            _validate_binding(static, binding, by_id)
            by_id[binding.provider_id] = binding
        self._static = static
        self._by_id = by_id
        self._ordered = tuple(
            by_id[descriptor.provider_id]
            for descriptor in static.all()
            if descriptor.provider_id in by_id
        )
        self._freshness_views: Mapping[str, Mapping[str, FreshnessSource]] = (
            MappingProxyType(
                {
                    binding.provider_id: MappingProxyType(dict(binding.freshness))
                    for binding in self._ordered
                }
            )
        )
        self._resolved: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()

    @property
    def static(self) -> ProviderRegistry:
        return self._static

    def binding(self, provider_id: str) -> ProviderRuntimeBinding:
        """Return a provider's binding; an unbound provider raises KeyError."""
        return self._by_id[provider_id]

    def job_owners(self) -> Mapping[str, ProviderJobOwner]:
        return self._factory_mapping("job_owner", lambda binding: binding.job_owner)

    def schedule_policies(self) -> Mapping[str, Mapping[str, ProviderSchedulePolicy]]:
        """Return policies keyed by "daily" and "startup", each in that order."""
        return MappingProxyType(
            {
                "daily": self._scheduled(self._static.daily_order()),
                "startup": self._scheduled(self._static.startup_order()),
            }
        )

    def freshness_sources(self) -> Mapping[str, Mapping[str, FreshnessSource]]:
        return self._freshness_views

    def resync_handlers(self) -> Mapping[str, FullResyncHandler]:
        return self._factory_mapping("full_resync", lambda binding: binding.full_resync)

    def synchronous_refreshes(self) -> Mapping[str, SynchronousRefresh]:
        return self._factory_mapping(
            "synchronous_refresh", lambda binding: binding.synchronous_refresh
        )

    def configured_for_job(self, job_type: str) -> tuple[str, ...]:
        """Return the bound providers that accept the job type and are configured now."""
        return tuple(
            binding.provider_id
            for binding in self._ordered
            if self._static.supports_job(binding.provider_id, job_type)
            and binding.configured()
        )

    def running_probes(self) -> Mapping[str, Callable[[], bool]]:
        probes: dict[str, Callable[[], bool]] = {}
        for binding in self._ordered:
            if binding.running_probe is not None:
                probes[binding.provider_id] = binding.running_probe
        return MappingProxyType(probes)

    def _scheduled(
        self, order: tuple[str, ...]
    ) -> Mapping[str, ProviderSchedulePolicy]:
        policies: dict[str, ProviderSchedulePolicy] = {}
        for provider_id in order:
            binding = self._by_id.get(provider_id)
            if binding is not None and binding.schedule is not None:
                policies[provider_id] = self._resolve(
                    "schedule", provider_id, binding.schedule
                )
        return MappingProxyType(policies)

    def _factory_mapping(
        self,
        kind: str,
        factory_of: Callable[[ProviderRuntimeBinding], Callable[[], _T] | None],
    ) -> Mapping[str, _T]:
        values: dict[str, _T] = {}
        for binding in self._ordered:
            factory = factory_of(binding)
            if factory is not None:
                values[binding.provider_id] = self._resolve(
                    kind, binding.provider_id, factory
                )
        return MappingProxyType(values)

    def _resolve(self, kind: str, provider_id: str, factory: Callable[[], _T]) -> _T:
        key = (kind, provider_id)
        with self._lock:
            if key not in self._resolved:
                self._resolved[key] = factory()
            value: _T = self._resolved[key]
            return value
