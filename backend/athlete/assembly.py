"""Composition for athlete records and completed-activity services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.activities.detail_store import ActivityDetailStore
from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.feedback import ActivityFeedbackService
from backend.activities.read_service import ActivityReadService
from backend.athlete.checkins import CheckinService
from backend.athlete.context import AthleteContextService
from backend.athlete.equipment import EquipmentService
from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager
from backend.db.repositories import (
    ActivityFeedbackRepository,
    CheckinRepository,
    CompetitionRepository,
    ProfileRepository,
    SnapshotRepository,
)
from backend.sync.snapshots import latest_snapshot


@dataclass(frozen=True)
class AthleteRepositories:
    activity_feedback: ActivityFeedbackRepository
    checkin: CheckinRepository
    profile: ProfileRepository
    key_values: Any
    snapshot: SnapshotRepository
    competition: CompetitionRepository


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
        database_manager: Callable[[], DatabaseManager]
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
        self._activity_feedback_repository = repositories.activity_feedback
        self._checkin_repository = repositories.checkin
        self._profile_repository = repositories.profile
        self._key_value_repository = repositories.key_values
        self._snapshot_repository = repositories.snapshot
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
            return latest_snapshot(db, self._snapshot_repository) or {}

    def equipment(self) -> EquipmentService:
        return EquipmentService(
            self._database_manager(),
            self.training_snapshot,
            self._local_date,
            self._utc_now,
        )

    def activity_feedback(self) -> ActivityFeedbackService:
        return ActivityFeedbackService(
            self._database_manager(),
            self._activity_feedback_repository,
            self._snapshot_repository,
        )

    def activity_read(self) -> ActivityReadService:
        return ActivityReadService(
            self._database_manager(),
            self._snapshot_repository,
            self.activity_feedback(),
            ActivityDetailStore(self._database_manager()),
            read_equipment=lambda: self.equipment().read(),
        )

    def duplicate_activity(self) -> DuplicateActivityService:
        return DuplicateActivityService(
            self._database_manager(),
            self._snapshot_repository,
            self._utc_now,
            self._event_buffer,
        )

    def checkin(self) -> CheckinService:
        return CheckinService(
            self._database_manager(), self._checkin_repository, self._local_date
        )

    def profile(self) -> ProfileService:
        return self.profile_for(self._database_manager())

    def profile_for(self, manager: DatabaseManager) -> ProfileService:
        """Bind the athlete clock to the existing shared manager cache owner."""
        return ProfileService(
            manager,
            self._profile_repository,
            self._key_value_repository,
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
