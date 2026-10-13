"""Compose the canonical read selector: the table readers and the legacy projection."""

from __future__ import annotations

from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_projection import CanonicalSnapshotProjection
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader


def build_canonical_read(
    *,
    legacy: CanonicalSnapshotProjection,
    key_values: KeyValueRepository,
) -> CanonicalReadSelector:
    return CanonicalReadSelector(
        legacy=legacy,
        table=CanonicalTableReader(),
        reprojecting_table=CanonicalTableReader(serve_older_versions=True),
        key_values=key_values,
    )
