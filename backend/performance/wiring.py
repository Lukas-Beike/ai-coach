"""Build the training report services from the application context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.app.context import AppContext
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.report_service import (
    BlockReviewSource,
    TrainingDerivedReadService,
    TrainingProfileSelectionService,
    TrainingRecordsService,
    TrainingReportReadService,
    TrainingReportServices,
    TrainingSeasonReadService,
)


@dataclass(frozen=True)
class PerformanceServices:
    training_reports: Callable[[], TrainingReportServices]


def build_performance(ctx: AppContext) -> PerformanceServices:
    """One session curve reader for the process; the report services fresh per call."""
    # One reader keeps the session curves across requests.
    power_curves = SessionCurveReader(ctx.canonical_table.session_activities)

    def local_today() -> Any:
        return ctx.clock.now().date()

    def checkins() -> Any:
        return ctx.athlete.checkin().list(365)

    def recovery() -> Any:
        state = ctx.public_state.performance_state_service().performance_state()
        return state["performance"].get("personal_recovery", {})

    def performance() -> Any:
        return ctx.public_state.performance_state_service().performance_state()[
            "performance"
        ]

    def timezone() -> str:
        return str(ctx.athlete.profile().get().get("timezone") or "UTC")

    def training_reports() -> TrainingReportServices:
        public = ctx.public_state
        athlete = ctx.athlete
        planning = ctx.planning_workflows
        canonical = public.canonical_performance_source()
        records = TrainingRecordsService(
            database_manager=ctx.database(),
            read_equipment=lambda: athlete.equipment().read(),
            read_record=lambda kind, record_id: (
                {
                    "record_type": kind,
                    "record": athlete.equipment().read(record_id)["items"][0],
                }
                if kind == "equipment"
                else {}
            ),
            canonical=canonical,
        )
        profiles = TrainingProfileSelectionService(
            local_today, canonical=canonical, curves=power_curves
        )
        return TrainingReportServices(
            records=records,
            profiles=profiles,
            report=TrainingReportReadService(
                read_plan=lambda: public.plan_state_service().read(local_only=True),
                read_checkins=checkins,
                read_feedback=lambda keys: athlete.activity_feedback().for_activity_ids(
                    keys
                ),
                today=local_today,
                canonical=canonical,
                session_feedback=lambda keys: (
                    athlete.activity_feedback().for_activity_ids(
                        keys, sessions_only=True
                    )
                ),
                now=ctx.clock.now,
                curve_records=profiles.curve_records,
                block_review=BlockReviewSource(
                    review=planning.block_review,
                    last_test=planning.last_completed_test,
                ),
                training_model=lambda: str(
                    athlete.profile().get().get("training_model") or ""
                ),
            ),
            derived=TrainingDerivedReadService(
                read_checkins=checkins,
                read_recovery=recovery,
                read_performance=performance,
                today=local_today,
                canonical=canonical,
            ),
            season=TrainingSeasonReadService(
                read_competitions=lambda: ctx.planning.competition().list(100),
                read_observations=records.observations,
                today=local_today,
                season_preparation=planning.season_preparation,
                season_source=public.season_source(),
            ),
            timezone=timezone,
        )

    return PerformanceServices(training_reports)
