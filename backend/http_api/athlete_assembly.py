"""Application composition for athlete records and completed-activity services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, tzinfo
from typing import Any

from backend.activities.activity_reference import ActivityReferences
from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.checkins import CheckinService
from backend.athlete.clock import AthleteLocalClock
from backend.athlete.context import AthleteContextService
from backend.athlete.equipment import EquipmentService
from backend.athlete.profile import ProfileService
from backend.athlete.zones import ZoneConfigurationService
from backend.performance.training_report import deduplicated_rows
from backend.runtime.ports import (
    ActivityRowReader,
    CanonicalTableServing,
    ProviderSnapshotReader,
)
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.weather.cache import invalidate_for_location_change


@dataclass(frozen=True)
class AthleteRepositories:
    activity_feedback: Any
    checkin: Any
    profile: Any
    key_values: Any
    snapshot_reader: ProviderSnapshotReader
    activity_rows: Callable[[], ActivityRowReader]
    table_serving: Callable[[], CanonicalTableServing]
    competition: Any


@dataclass(frozen=True)
class AthleteRuntime:
    utc_now: Callable[[], Any]
    local_date: Callable[[], Any]
    event_buffer: Any
    normalize_profile: Callable[[Any], Any]
    normalize_competition: Callable[[Any], Any]
    uuid_factory: Callable[[], Any]
    read_planned_units: Callable[[], list[dict[str, Any]]] = list


class AthleteDataAssembly:
    """Create fresh athlete and activity services over shared repositories."""

    @dataclass(frozen=True)
    class Inputs:
        database_manager: Callable[[], Any]
        profile_mutation_coordinator: Any
        repositories: AthleteRepositories
        runtime: AthleteRuntime

    def __init__(
        self,
        *,
        dependencies: AthleteDataAssembly.Inputs,
    ) -> None:
        repositories = dependencies.repositories
        runtime = dependencies.runtime
        self._database_manager = dependencies.database_manager
        self._profile_mutation_coordinator = dependencies.profile_mutation_coordinator
        self._activity_feedback_repository = repositories.activity_feedback
        self._checkin_repository = repositories.checkin
        self._profile_repository = repositories.profile
        self._key_value_repository = repositories.key_values
        self._snapshot_reader = repositories.snapshot_reader
        self._activity_rows = repositories.activity_rows
        self._table_serving = repositories.table_serving
        self._utc_now = runtime.utc_now
        self._local_date = runtime.local_date
        self._event_buffer = runtime.event_buffer
        self._competition_repository = repositories.competition
        self._normalize_profile = runtime.normalize_profile
        self._normalize_competition = runtime.normalize_competition
        self._uuid_factory = runtime.uuid_factory
        self._read_planned_units = runtime.read_planned_units

    def training_snapshot(self) -> dict[str, Any]:
        with self._database_manager().unit_of_work() as db:
            return self._snapshot_reader.latest_snapshot(db) or {}

    def activity_rows(self) -> tuple[dict[str, Any], ...]:
        with self._database_manager().unit_of_work() as db:
            return self._activity_rows().activity_rows(db)

    def equipment(self) -> EquipmentService:
        return EquipmentService(
            self._database_manager(),
            self.activity_rows,
            self._local_date,
            self._utc_now,
            deduplicated_rows,
            resolve_activity=ActivityReferences(self._database_manager()).resolve,
            gear_reader=CanonicalTableReader(),
        )

    def zones(self) -> ZoneConfigurationService:
        return ZoneConfigurationService(
            self._database_manager(), CanonicalTableReader(), self._utc_now
        )

    def activity_feedback(self) -> ActivityFeedbackService:
        return ActivityFeedbackService(
            self._database_manager(),
            self._activity_feedback_repository,
            self._activity_rows(),
            references=ActivityReferences(self._database_manager()),
        )

    def _athlete_zone(self) -> tzinfo:
        """The athlete's wall-clock zone from the saved profile."""
        return AthleteLocalClock(self.profile()).now().tzinfo or UTC

    def duplicate_inspector(self) -> DuplicateInspector:
        # Always the canonical tables, never the selector's snapshot projection,
        # and only while the tables serve reads (see DuplicateInspector).
        return DuplicateInspector(
            self._database_manager(),
            CanonicalTableReader(),
            self._athlete_zone,
            self._table_serving(),
        )

    def duplicate_activity(self) -> DuplicateActivityService:
        return DuplicateActivityService(
            self._database_manager(),
            self.duplicate_inspector(),
            self._utc_now,
            self._event_buffer,
            references=ActivityReferences(self._database_manager()),
        )

    def checkin(self) -> CheckinService:
        return CheckinService(
            self._database_manager(), self._checkin_repository, self._local_date
        )

    def profile(self) -> ProfileService:
        return self.profile_for(self._database_manager())

    def profile_for(self, manager: Any) -> ProfileService:
        """Bind the athlete clock to the existing shared manager cache owner."""
        return ProfileService(
            manager,
            self._profile_repository,
            self._key_value_repository,
            on_location_changed=invalidate_for_location_change,
            mutation_coordinator=self._profile_mutation_coordinator,
        )

    def context(self) -> AthleteContextService:
        return AthleteContextService(
            self._database_manager(),
            self.profile(),
            self._competition_repository,
            self._normalize_profile,
            self._normalize_competition,
            self._utc_now,
            self._uuid_factory,
        )
