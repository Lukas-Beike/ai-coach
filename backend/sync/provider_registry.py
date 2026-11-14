"""Queries over the provider table for synchronization.

Provider data lives in backend/sync/provider_table.py. This module names no
provider, so it stays free of the provider literals the coupling guard
forbids. Lookups take provider identifiers from the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from backend.sync.provider_table import (
    DEFAULT_MAX_SYNC_DAYS,
    DEFAULT_PROVIDER_DESCRIPTORS,
    Capability,
    FreshnessArea,
    ProviderDescriptor,
)


class ProviderRegistry:
    """Immutable, ordered view over provider descriptors."""

    def __init__(self, descriptors: Iterable[ProviderDescriptor]) -> None:
        self._descriptors = tuple(descriptors)
        self._by_id = {d.provider_id: d for d in self._descriptors}
        self._freshness_areas = tuple(
            (d.provider_id, area)
            for d in self._descriptors
            for area in d.freshness_areas
        )

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

    def accepts_sync_days(self, provider_id: str, days: int, all_days: int) -> bool:
        """Return whether ``days`` is a valid sync window for the provider.

        ``all_days`` marks the whole history; any other window must lie between
        one day and the provider's sync-window limit.
        """
        return days == all_days or 1 <= days <= self.max_sync_days(provider_id)

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

    def coach_write_targets(self) -> tuple[str, ...]:
        """Return the output-only providers a Coach request may name for a write.

        They accept competition and workout writes but are never refreshed.
        """
        return tuple(
            descriptor.provider_id
            for descriptor in self._descriptors
            if Capability.COMPETITIONS in descriptor.capabilities
            and descriptor.coach_rank is None
        )

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
