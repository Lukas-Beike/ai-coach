"""Compose the canonical backfill: the use case, its worker and its status reader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.performance.session_rpe_load import FeedbackLookup
from backend.performance.source_policy import NO_PREFERENCES
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.activity_detail_backfill import ActivityDetailBackfill
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.activity_detail_retirement import ActivityDetailRetirement
from backend.sync.canonical_backfill import DEFAULT_BATCH_SIZE, CanonicalBackfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.local_load import LocalLoadStage, Preferences
from backend.sync.session_analysis_stage import PlannedUnits, SessionAnalysisStage
from backend.sync.session_metrics import SessionMetricsStage


@dataclass(frozen=True, slots=True)
class CanonicalBackfillAssembly:
    worker: CanonicalBackfillWorker
    status_reader: CanonicalBackfill
    detail_backfill: ActivityDetailBackfill
    detail_retirement: ActivityDetailRetirement
    local_load: LocalLoadStage
    session_metrics: SessionMetricsStage
    session_analysis: SessionAnalysisStage


def build_canonical_backfill(
    *,
    database: Callable[[], Any],
    key_values: KeyValueRepository,
    zone_provider: Callable[[], tzinfo | None],
    maintenance_gate: MaintenanceGate,
    clock: Callable[[], str],
    source_preferences: Preferences = lambda _db: NO_PREFERENCES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session_feedback: FeedbackLookup | None = None,
    planned_units: PlannedUnits = list,
    athlete_sex: Callable[[Any], str | None] = lambda _db: None,
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
    # Runs first after the canonical backfill, so a failing detail stage never
    # blocks it: reconciles the local session load (card M6) on every pass.
    local_load = LocalLoadStage(
        key_values=key_values,
        zone_provider=zone_provider,
        clock=clock,
        preferences=source_preferences,
        session_feedback=session_feedback,
        athlete_sex=athlete_sex,
    )
    # Local session metrics (card M8) from summaries and stored streams.
    session_metrics = SessionMetricsStage(
        key_values=key_values, zone_provider=zone_provider, clock=clock
    )
    # The one canonical session analysis per session (#1685), after M8.
    session_analysis = SessionAnalysisStage(
        key_values=key_values,
        zone_provider=zone_provider,
        clock=clock,
        planned_units=planned_units,
        preferences=source_preferences,
    )
    worker = CanonicalBackfillWorker(
        backfill=backfill,
        database=database,
        maintenance_gate=maintenance_gate,
        followups=(
            local_load,
            session_metrics,
            detail_backfill,
            # After the legacy detail copy, so its target snapshots carry over.
            session_analysis,
            detail_retirement,
        ),
    )
    return CanonicalBackfillAssembly(
        worker=worker,
        status_reader=backfill,
        detail_backfill=detail_backfill,
        detail_retirement=detail_retirement,
        local_load=local_load,
        session_metrics=session_metrics,
        session_analysis=session_analysis,
    )
