"""Compose the canonical backfill: the use case, its worker and its status reader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.activity_detail_backfill import ActivityDetailBackfill
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.canonical_backfill import DEFAULT_BATCH_SIZE, CanonicalBackfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker


@dataclass(frozen=True, slots=True)
class CanonicalBackfillAssembly:
    worker: CanonicalBackfillWorker
    status_reader: CanonicalBackfill
    detail_backfill: ActivityDetailBackfill


def build_canonical_backfill(
    *,
    database: Callable[[], Any],
    key_values: KeyValueRepository,
    zone_provider: Callable[[], tzinfo | None],
    maintenance_gate: MaintenanceGate,
    clock: Callable[[], str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> CanonicalBackfillAssembly:
    backfill = CanonicalBackfill(
        key_values=key_values,
        zone_provider=zone_provider,
        clock=clock,
        batch_size=batch_size,
    )
    # Runs after the canonical backfill completes, with its own state key.
    detail_backfill = ActivityDetailBackfill(
        key_values=key_values,
        writer=CanonicalDetailWriter(),
        clock=clock,
    )
    worker = CanonicalBackfillWorker(
        backfill=backfill,
        database=database,
        maintenance_gate=maintenance_gate,
        followups=(detail_backfill,),
    )
    return CanonicalBackfillAssembly(
        worker=worker, status_reader=backfill, detail_backfill=detail_backfill
    )
