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


def build_performance(
    ctx: AppContext,
    *,
    session_activities: Callable[..., Any],
    plan_state: Callable[[], Any],
    performance_state: Callable[[], Any],
    canonical_performance_source: Callable[[], Any],
    season_source: Callable[[], Any],
    block_review: Callable[..., dict[str, Any]],
    last_completed_test: Callable[..., str | None],
    season_preparation: Callable[..., dict[str, Any]],
) -> PerformanceServices:
    """One session curve reader for the process; the report services fresh per call.

    The composition root passes the HTTP public-state projections and the
    planning functions the reports read, so this domain imports neither layer.
    """
    # One reader keeps the session curves across requests.
    power_curves = SessionCurveReader(session_activities)

    def local_today() -> Any:
        return ctx.clock.now().date()

    def checkins() -> Any:
        return ctx.athlete.checkin().list(365)

    def recovery() -> Any:
        state = performance_state().performance_state()
        return state["performance"].get("personal_recovery", {})

    def performance() -> Any:
        return performance_state().performance_state()["performance"]

    def timezone() -> str:
        return str(ctx.athlete.profile().get().get("timezone") or "UTC")

    def training_reports() -> TrainingReportServices:
        athlete = ctx.athlete
        canonical = canonical_performance_source()
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
                read_plan=lambda: plan_state().read(local_only=True),
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
                    review=block_review,
                    last_test=last_completed_test,
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
                season_preparation=season_preparation,
                season_source=season_source(),
            ),
            timezone=timezone,
        )

    return PerformanceServices(training_reports)
