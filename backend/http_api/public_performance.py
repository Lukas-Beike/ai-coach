"""Public performance and athlete-feedback state projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.performance import context as performance_context
from backend.performance.canonical_body import CanonicalBodyInputs, read_body_inputs
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    inputs_for_snapshot,
    performance_options,
    read_once,
    read_performance_inputs,
    resolve_reader,
)
from backend.performance.chart_history import analysis_history
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
            return self.from_snapshot(self._sync_state_repository.latest_snapshot())
        today = self._today()
        # One read-only snapshot: the performance snapshot, the Garmin snapshot,
        # the canonical reads and the profile/Garmin projection share one
        # connection, so a concurrent sync cannot mix revisions and the request
        # never waits for the writer. The chosen source serves both body and
        # load reads.
        with source.database_manager().read_snapshot() as db:
            snapshot = self._sync_state_repository.latest_snapshot()
            garmin = self._garmin_payload_service.recent_view_in(db)
            reader = read_once(resolve_reader(source.observation_reader(), db))
            canonical = read_performance_inputs(
                reader,
                db,
                snapshot,
                activity_reader=source.activity_row_reader(),
                as_of=today,
            )
            body = _body_inputs(source, reader, db, today)
            return self._project(
                snapshot, garmin, canonical, body, today, observations=reader
            )

    def canonical_inputs(
        self, db: Any, snapshot: Any
    ) -> CanonicalPerformanceInputs | None:
        """Read the load inputs inside the transaction that read ``snapshot``."""
        return inputs_for_snapshot(self._canonical, db, snapshot, as_of=self._today())

    def from_snapshot(
        self,
        snapshot: dict[str, Any],
        canonical: CanonicalPerformanceInputs | None = None,
    ) -> dict[str, Any]:
        """Project a snapshot and the inputs a larger state request read with it."""
        return self._project(
            snapshot,
            self._garmin_payload_service.recent_view(),
            canonical,
            None,
            self._today(),
        )

    def _project(
        self,
        snapshot: dict[str, Any],
        garmin: dict[str, Any],
        canonical: CanonicalPerformanceInputs | None,
        body: CanonicalBodyInputs | None,
        today: date,
        *,
        observations: ObservationReader | None = None,
    ) -> dict[str, Any]:
        profile = self._profile_service.get()
        performance = performance_context.current_performance_context(
            snapshot,
            garmin,
            profile,
            today,
            **performance_options(canonical),
        )
        timezone = str(profile.get("timezone") or "UTC")
        performance = {
            **performance,
            "history": analysis_history(
                snapshot, garmin, today, canonical_body=body, canonical=canonical
            ),
            # UI-only: the load tab's period selection picks the matching window.
            "training_focus_periods": {
                period: training_focus(
                    snapshot,
                    garmin,
                    today,
                    timezone,
                    activity_rows=None
                    if canonical is None
                    else canonical.activity_rows,
                    days=days,
                )
                for period, days in (("fortnight", 14), ("twelveWeeks", 84))
            },
        }
        return {
            "performance": performance,
            ProviderId.GARMIN.value: (
                self._garmin_projection_service.public_state(garmin)
                if observations is None
                else self._garmin_projection_service.public_state(
                    garmin, observations=observations
                )
            ),
        }


def _body_inputs(
    source: CanonicalPerformanceSource,
    reader: ObservationReader,
    db: Any,
    today: date,
) -> CanonicalBodyInputs | None:
    """Read canonical weight and body fat inside the snapshot transaction, when gated on."""
    if source.serving is None:
        return None
    return read_body_inputs(reader, source.serving(), db, today)


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
