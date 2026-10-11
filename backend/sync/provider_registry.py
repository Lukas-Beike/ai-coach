"""Registry of configured provider descriptors for synchronization.

Provider data lives in backend/providers/descriptors.py. This module names no
provider, so it stays free of provider literals and needs no coupling baseline
entry. Lookups take provider identifiers from the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from backend.providers.descriptors import (
    DEFAULT_MAX_SYNC_DAYS,
    DEFAULT_PROVIDER_DESCRIPTORS,
    Capability,
    FreshnessArea,
    ProviderDescriptor,
)


def _reject_duplicate_routes(descriptors: tuple[ProviderDescriptor, ...]) -> None:
    manual = [
        descriptor.manual_sync.path
        for descriptor in descriptors
        if descriptor.manual_sync is not None
    ]
    if len(set(manual)) != len(manual):
        raise ValueError("duplicate manual sync route")
    full_resync = [
        descriptor.full_resync_path
        for descriptor in descriptors
        if descriptor.full_resync_path is not None
    ]
    if len(set(full_resync)) != len(full_resync):
        raise ValueError("duplicate full resync route")


class ProviderRegistry:
    """Immutable, ordered view over provider descriptors."""

    def __init__(self, descriptors: Iterable[ProviderDescriptor]) -> None:
        ordered = tuple(descriptors)
        by_id: dict[str, ProviderDescriptor] = {}
        freshness_areas: list[tuple[str, FreshnessArea]] = []
        seen_areas: set[tuple[str, str]] = set()
        for descriptor in ordered:
            if descriptor.provider_id in by_id:
                raise ValueError(
                    f"duplicate provider descriptor: {descriptor.provider_id}"
                )
            by_id[descriptor.provider_id] = descriptor
            for area in descriptor.freshness_areas:
                key = (descriptor.provider_id, area.area)
                if key in seen_areas:
                    raise ValueError(f"duplicate freshness area: {key[0]} {key[1]}")
                seen_areas.add(key)
                freshness_areas.append((descriptor.provider_id, area))
        _reject_duplicate_routes(ordered)
        self._descriptors = ordered
        self._by_id = by_id
        self._freshness_areas = tuple(freshness_areas)

    def get(self, provider_id: str) -> ProviderDescriptor:
        """Return a descriptor; an unknown provider raises KeyError."""
        return self._by_id[provider_id]

    def all(self) -> tuple[ProviderDescriptor, ...]:
        return self._descriptors

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def freshness_areas(self) -> tuple[tuple[str, FreshnessArea], ...]:
        return self._freshness_areas

    def ids_with(self, capability: Capability) -> tuple[str, ...]:
        return tuple(
            descriptor.provider_id
            for descriptor in self._descriptors
            if capability in descriptor.capabilities
        )

    def max_sync_days(
        self, provider_id: str, default: int = DEFAULT_MAX_SYNC_DAYS
    ) -> int:
        """Return the provider's sync-window limit, or ``default`` when unknown.

        Non-text identifiers fall back to the default instead of raising, which
        matches the previous literal rule for every input.
        """
        if not isinstance(provider_id, str):
            return default
        descriptor = self._by_id.get(provider_id)
        if descriptor is None:
            return default
        return descriptor.max_sync_days

    def supports_job(self, provider_id: str, job_type: str) -> bool:
        """Return whether the provider accepts the job type; unknown ids are False."""
        descriptor = self._lookup(provider_id)
        return (
            descriptor is not None
            and isinstance(job_type, str)
            and job_type in descriptor.job_types
        )

    def refresh_fields(self, provider_id: str) -> frozenset[str]:
        """Return the refresh payload fields; an unknown provider raises KeyError."""
        return self._by_id[provider_id].refresh_fields

    def sync_period_defaults(self) -> dict[str, int]:
        """Return default sync windows for providers that declare one."""
        defaults: dict[str, int] = {}
        for descriptor in self._descriptors:
            if descriptor.default_sync_days is not None:
                defaults[descriptor.provider_id] = descriptor.default_sync_days
        return defaults

    def daily_order(self) -> tuple[str, ...]:
        """Return provider ids in daily scheduling order."""
        return self._ranked_ids(lambda descriptor: descriptor.schedule.daily_rank)

    def startup_order(self) -> tuple[str, ...]:
        """Return provider ids in startup scheduling order."""
        return self._ranked_ids(lambda descriptor: descriptor.schedule.startup_rank)

    def daily_marker_ids(self) -> frozenset[str]:
        """Return the providers that keep daily attempt and success markers."""
        return frozenset(
            descriptor.provider_id
            for descriptor in self._descriptors
            if descriptor.schedule.daily_marker
        )

    def coach_refresh_targets(self) -> tuple[str, ...]:
        """Return the providers the Coach can refresh, in Coach rank order."""
        return self._ranked_ids(lambda descriptor: descriptor.coach_rank)

    def resync_key_map(self) -> dict[str, tuple[str, ...]]:
        """Return full-resync state keys for providers that declare them."""
        keys: dict[str, tuple[str, ...]] = {}
        for descriptor in self._descriptors:
            if descriptor.resync_keys:
                keys[descriptor.provider_id] = descriptor.resync_keys
        return keys

    def manual_routes(self) -> tuple[tuple[str, str], ...]:
        """Return (path, provider_id) for each manual sync route."""
        routes: list[tuple[str, str]] = []
        for descriptor in self._descriptors:
            if descriptor.manual_sync is not None:
                routes.append((descriptor.manual_sync.path, descriptor.provider_id))
        return tuple(routes)

    def full_resync_routes(self) -> tuple[tuple[str, str], ...]:
        """Return (path, provider_id) for each full-resync route."""
        routes: list[tuple[str, str]] = []
        for descriptor in self._descriptors:
            if descriptor.full_resync_path is not None:
                routes.append((descriptor.full_resync_path, descriptor.provider_id))
        return tuple(routes)

    def period_error_message(self, provider_id: str) -> str:
        """Return the German sync-period validation message for a provider."""
        return (
            f"Der Zeitraum für {provider_id} muss -1 oder zwischen 1 und "
            f"{self.max_sync_days(provider_id)} Tagen liegen."
        )

    def _lookup(self, provider_id: object) -> ProviderDescriptor | None:
        if not isinstance(provider_id, str):
            return None
        return self._by_id.get(provider_id)

    def _ranked_ids(
        self, rank_of: Callable[[ProviderDescriptor], int | None]
    ) -> tuple[str, ...]:
        ranked: list[tuple[int, int, str]] = []
        for index, descriptor in enumerate(self._descriptors):
            rank = rank_of(descriptor)
            if rank is not None:
                ranked.append((rank, index, descriptor.provider_id))
        return tuple(provider_id for _, _, provider_id in sorted(ranked))


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry(DEFAULT_PROVIDER_DESCRIPTORS)
