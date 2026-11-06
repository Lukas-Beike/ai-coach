"""Compose the canonical backfill: the use case, its worker and its status reader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.performance.source_policy import NO_PREFERENCES
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.activity_detail_backfill import ActivityDetailBackfill
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.activity_detail_retirement import ActivityDetailRetirement
from backend.sync.canonical_backfill import DEFAULT_BATCH_SIZE, CanonicalBackfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.local_load import LocalLoadStage, Preferences


@dataclass(frozen=True, slots=True)
class CanonicalBackfillAssembly:
    worker: CanonicalBackfillWorker
    status_reader: CanonicalBackfill
    detail_backfill: ActivityDetailBackfill
    detail_retirement: ActivityDetailRetirement
    local_load: LocalLoadStage


def build_canonical_backfill(
    *,
    database: Callable[[], Any],
    key_values: KeyValueRepository,
    zone_provider: Callable[[], tzinfo | None],
    maintenance_gate: MaintenanceGate,
    clock: Callable[[], str],
    source_preferences: Preferences = lambda _db: NO_PREFERENCES,
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
    # Runs after the detail backfill: deletes the kv records canonical proves.
    detail_retirement = ActivityDetailRetirement(key_values=key_values, clock=clock)
    # Runs last: reconciles the local session load (card M6) on every pass.
    local_load = LocalLoadStage(
        key_values=key_values,
        zone_provider=zone_provider,
        clock=clock,
        preferences=source_preferences,
    )
    worker = CanonicalBackfillWorker(
        backfill=backfill,
        database=database,
        maintenance_gate=maintenance_gate,
        followups=(detail_backfill, detail_retirement, local_load),
    )
    return CanonicalBackfillAssembly(
        worker=worker,
        status_reader=backfill,
        detail_backfill=detail_backfill,
        detail_retirement=detail_retirement,
        local_load=local_load,
    )
