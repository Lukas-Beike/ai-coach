"""Public performance and athlete-feedback state projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.performance import context as performance_context
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    inputs_for_snapshot,
    read_once,
    read_performance_inputs,
    resolve_reader,
    with_read_status,
)
from backend.performance.chart_history import analysis_history
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS, GarminSyncStatus
from backend.performance.training_focus import training_focus
from backend.runtime.ports import ObservationReader


class PublicPerformanceStateService:
    """Project persisted performance and Garmin data into public API state."""

    def __init__(
        self,
        sync_state_repository: Any,
        garmin_payload_service: Any,
        profile_service: Any,
        garmin_projection_service: Any,
        today: Callable[[], date],
        canonical: CanonicalPerformanceSource | None = None,
    ) -> None:
        self._sync_state_repository = sync_state_repository
        self._garmin_payload_service = garmin_payload_service
        self._profile_service = profile_service
        self._garmin_projection_service = garmin_projection_service
        self._today = today
        self._canonical = canonical

    def performance_state(self) -> dict[str, Any]:
        source = self._canonical
        if source is None:
            return self.from_inputs(None)
        today = self._today()
        # One read-only snapshot: the canonical reads, the Garmin sync status and
        # the profile/Garmin projection share one connection, so a concurrent sync
        # cannot mix revisions and the request never waits for the writer. The
        # chosen source serves both body and load reads.
        with source.database_manager().read_snapshot() as db:
            # Remaining snapshot read: the power curve has no metric kind (#1416).
            snapshot = self._sync_state_repository.latest_snapshot()
            garmin = self._garmin_payload_service.sync_status_in(db)
            reader = read_once(resolve_reader(source.observation_reader(), db))
            canonical = with_read_status(
                source,
                db,
                read_performance_inputs(
                    reader,
                    db,
                    activity_reader=source.activity_summary_reader(),
                    as_of=today,
                    include_power_curve=True,
                ),
            )
            return self._project(
                snapshot, garmin, canonical, today, observations=reader
            )

    def canonical_inputs(self, db: Any) -> CanonicalPerformanceInputs | None:
        """Read the load inputs inside the caller's snapshot transaction."""
        return inputs_for_snapshot(
            self._canonical, db, as_of=self._today(), include_power_curve=True
        )

    def from_inputs(
        self,
        canonical: CanonicalPerformanceInputs | None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Project the inputs a larger state request read in its own transaction.

        ``snapshot`` is that request's stored snapshot; it supplies only the power
        curve and is read here when not given.
        """
        if snapshot is None:
            snapshot = self._sync_state_repository.latest_snapshot()
        return self._project(
            snapshot,
            self._garmin_payload_service.sync_status(),
            canonical,
            self._today(),
        )

    def _project(
        self,
        snapshot: dict[str, Any] | None,
        garmin: GarminSyncStatus,
        canonical: CanonicalPerformanceInputs | None,
        today: date,
        *,
        observations: ObservationReader | None = None,
    ) -> dict[str, Any]:
        """Project canonical values; ``snapshot`` supplies only the power curve."""
        profile = self._profile_service.get()
        inputs = canonical or EMPTY_PERFORMANCE_INPUTS
        status = garmin
        if inputs.pending:
            # Nothing is served before the first completed backfill: no history,
            # focus or Garmin values and no power curve. The Garmin connection
            # status stays.
            snapshot, garmin = {}, NO_GARMIN_SYNC_STATUS
        performance = performance_context.current_performance_context(
            garmin, profile, today, canonical=inputs
        )
        timezone = str(profile.get("timezone") or "UTC")
        performance = {
            **performance,
            "history": analysis_history(snapshot, garmin, today, canonical=inputs),
            # UI-only: the load tab's period selection picks the matching window.
            "training_focus_periods": {
                period: training_focus(
                    garmin,
                    today,
                    timezone,
                    activities=inputs.activities or (),
                    days=days,
                )
                for period, days in (("fortnight", 14), ("twelveWeeks", 84))
            },
        }
        return {
            "performance": performance,
            ProviderId.GARMIN.value: (
                self._garmin_projection_service.public_state(status)
                if observations is None
                else self._garmin_projection_service.public_state(
                    status, observations=observations
                )
            ),
        }


class PublicFeedbackStateService:
    """Project local check-ins and activity feedback into public API state."""

    def __init__(self, checkin_service: Any, activity_feedback_service: Any) -> None:
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service

    def feedback_state(
        self, checkins: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return {
            "checkins": checkins
            if checkins is not None
            else self._checkin_service.list(30),
            "local_feedback": self._checkin_service.context(),
            "activity_feedback": self._activity_feedback_service.context(),
        }
