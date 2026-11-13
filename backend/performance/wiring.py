"""Build the training report, athlete data and activity read services."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.activities.activity_reference import ActivityReferences
from backend.activities.feedback import ActivityFeedbackService
from backend.activities.session_corrections import SessionCorrectionService
from backend.activities.zone_settings import effective_zone_configuration
from backend.app.context import AppContext
from backend.athlete.checkins import CheckinService
from backend.athlete.equipment import EquipmentService
from backend.athlete.equipment_history import equipment_history_records
from backend.athlete.profile import ProfileService
from backend.athlete.zones import ZoneConfigurationService
from backend.canonical.activity_summary import ActivitySummary
from backend.canonical.vocabulary import ProviderId
from backend.db.repositories import CheckinRepository, ProfileRepository
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.first_threshold_service import FirstThresholdService
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
from backend.performance.source_policy import (
    PREFERENCE_PROFILE_FIELDS,
    preferences_from_profile,
)
from backend.weather.cache import invalidate_for_location_change

_PROVIDER_IDS = frozenset(provider.value for provider in ProviderId)


@dataclass(frozen=True)
class PerformanceServices:
    training_reports: Callable[[], TrainingReportServices]
    # The session curve records over the one reader, without the report bundle;
    # the last read is shared while its inputs are unchanged, as read-only records.
    curve_records: Callable[[int], Sequence[Mapping[str, Any]]]


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

    def curve_records(days: int) -> Sequence[Mapping[str, Any]]:
        return TrainingProfileSelectionService(
            local_today, canonical=canonical_performance_source(), curves=power_curves
        ).curve_records(days, shared=True)

    return PerformanceServices(training_reports, curve_records)


@dataclass(frozen=True)
class AthleteDataServices:
    activity_summaries: Callable[[], tuple[ActivitySummary, ...]]
    equipment: Callable[[], EquipmentService]
    equipment_history: Callable[[], dict[str, Any]]
    zones: Callable[[], ZoneConfigurationService]
    activity_feedback: Callable[[], ActivityFeedbackService]
    session_corrections: Callable[[], SessionCorrectionService]
    checkin: Callable[[], CheckinService]
    first_threshold: Callable[[], FirstThresholdService]
    profile: Callable[[], ProfileService]
    # Binds the athlete clock to the existing shared manager cache owner.
    profile_for: Callable[[Any], ProfileService]


def build_athlete_data(
    *,
    database_manager: Callable[[], Any],
    key_values: Any,
    activity_feedback_repository: Any,
    profile_mutation_coordinator: Any,
    utc_now: Callable[[], Any],
    local_date: Callable[[], Any],
    event_buffer: Any,
    activity_rows: Callable[[], Any],
    table_reader: Callable[[], Any],
    run_lthr: Callable[[], Any],
    # Called when an input of the local session load (card M6) changes: a local
    # zone configuration, a session correction or a preferred threshold source.
    load_inputs_changed: Callable[[], None],
    # A local zone change can change the thresholds exported to Intervals.icu.
    thresholds_changed: Callable[[], None],
    # The stale-threshold and Garmin SDK warning shown with the zones (#1768).
    threshold_warnings: Callable[[], dict[str, Any] | None],
) -> AthleteDataServices:
    """Fresh athlete and activity services per call over shared repositories.

    Built before the application context: the athlete clock reads the profile
    service and the context holds that clock, so nothing here reads the context.
    """
    profiles = ProfileRepository(key_values)
    checkins = CheckinRepository(utc_now)

    def activity_summaries() -> tuple[ActivitySummary, ...]:
        with database_manager().reader() as db:
            return activity_rows().activity_summaries(db)

    def zones_changed() -> None:
        load_inputs_changed()
        thresholds_changed()

    def profile_changed(
        previous: dict[str, Any], current: dict[str, Any], **kwargs: Any
    ) -> None:
        """Invalidate location caches; a new preferred source changes local loads.

        A new time zone moves the local day the stored loads are dated by (M6, M7);
        the sex chooses the M6 TRIMP constants.
        """
        invalidate_for_location_change(previous, current, **kwargs)
        if any(
            previous.get(field) != current.get(field)
            for field in (*PREFERENCE_PROFILE_FIELDS.values(), "timezone", "sex")
        ):
            load_inputs_changed()

    def profile_for(manager: Any) -> ProfileService:
        return ProfileService(
            manager,
            profiles,
            key_values,
            on_location_changed=profile_changed,
            mutation_coordinator=profile_mutation_coordinator,
            run_lthr_on=lambda day: run_lthr().on(day),
        )

    def profile() -> ProfileService:
        return profile_for(database_manager())

    return AthleteDataServices(
        activity_summaries=activity_summaries,
        equipment=lambda: EquipmentService(
            database_manager(),
            activity_summaries,
            local_date,
            utc_now,
            gear_reader=table_reader(),
        ),
        equipment_history=lambda: equipment_history_records(
            utc_now, activity_summaries
        ),
        zones=lambda: ZoneConfigurationService(
            database_manager(),
            table_reader(),
            utc_now,
            today=local_date,
            effective_zone=effective_zone_configuration,
            on_change=zones_changed,
            threshold_warnings=threshold_warnings,
        ),
        activity_feedback=lambda: ActivityFeedbackService(
            database_manager(),
            activity_feedback_repository,
            references=ActivityReferences(database_manager()),
            on_change=load_inputs_changed,
        ),
        session_corrections=lambda: SessionCorrectionService(
            database_manager(), utc_now, event_buffer, on_change=load_inputs_changed
        ),
        checkin=lambda: CheckinService(database_manager(), checkins, local_date),
        first_threshold=lambda: FirstThresholdService(
            database_manager(),
            profile(),
            lambda: run_lthr().day_resolver(),
            local_date,
        ),
        profile=profile,
        profile_for=profile_for,
    )


@dataclass(frozen=True)
class ActivityReadServices:
    activity_read: Callable[[], ActivityAnalysisReadService]


def build_activity_reads(
    ctx: AppContext,
    *,
    session_activities: Callable[..., Any],
    refreshable_providers: Callable[[], Iterable[str]],
) -> ActivityReadServices:
    """Fresh activity read services over the canonical read state of the context.

    The canonical read reports its read state, so the detail's performance block
    is marked pending or carries the compact-only activity gap.
    ``refreshable_providers`` names the providers that can load details now.
    """

    def refreshable() -> frozenset[ProviderId]:
        return frozenset(
            ProviderId(provider)
            for provider in refreshable_providers()
            if provider in _PROVIDER_IDS
        )

    def activity_read() -> ActivityAnalysisReadService:
        manager = ctx.database()
        athlete = ctx.athlete
        return ActivityAnalysisReadService(
            manager,
            ctx.canonical_read,
            athlete.activity_feedback(),
            read_equipment=lambda activity_id: athlete.equipment().read(
                activity_id=activity_id
            ),
            references=ActivityReferences(manager),
            canonical=CanonicalPerformanceSource(
                ctx.database,
                lambda: ctx.canonical_read,
                serving=lambda: ctx.canonical_read,
                activity_summaries=lambda: ctx.canonical_read,
                coverage=lambda: ctx.canonical_read,
                source_preferences=lambda db: preferences_from_profile(
                    athlete.profile().get_from_db(db)
                ),
            ),
            session_records=session_activities,
            refreshable=refreshable,
        )

    return ActivityReadServices(activity_read)
