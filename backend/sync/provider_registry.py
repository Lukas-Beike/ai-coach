"""Registry of configured provider descriptors for synchronization.

Provider data lives in backend/providers/descriptors.py. This module names no
provider, so it stays free of provider literals and needs no coupling baseline
entry. Lookups take provider identifiers from the caller.
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.providers.descriptors import (
    DEFAULT_MAX_SYNC_DAYS,
    DEFAULT_PROVIDER_DESCRIPTORS,
    Capability,
    FreshnessArea,
    ProviderDescriptor,
)


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


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry(DEFAULT_PROVIDER_DESCRIPTORS)
