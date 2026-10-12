"""Compose the canonical read selector: table reader, parity check and switch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.runtime.ports import ProviderSnapshotReader
from backend.sync.canonical_parity import CanonicalParity
from backend.sync.canonical_projection import CanonicalSnapshotProjection
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader


def build_canonical_read(
    *,
    legacy: CanonicalSnapshotProjection,
    key_values: KeyValueRepository,
    snapshots: ProviderSnapshotReader,
    fingerprint: Callable[[dict[str, Any]], str],
) -> CanonicalReadSelector:
    table = CanonicalTableReader()
    parity = CanonicalParity(
        legacy=legacy,
        table=table,
        snapshots=snapshots,
        fingerprint=fingerprint,
        zone=legacy.zone,
    )
    return CanonicalReadSelector(
        legacy=legacy,
        table=table,
        parity=parity,
        key_values=key_values,
    )
