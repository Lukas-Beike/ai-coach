"""Composition for athlete records and completed-activity services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.feedback import ActivityFeedbackService
from backend.activities.read_service import ActivityReadService
from backend.athlete.checkins import CheckinService
from backend.athlete.context import AthleteContextService
from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager
from backend.db.repositories import (
    ActivityFeedbackRepository,
    CheckinRepository,
    ProfileRepository,
    SnapshotRepository,
    CompetitionRepository,
)


class AthleteDataAssembly:
    """Create fresh athlete and activity services over shared repositories."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        activity_feedback_repository: ActivityFeedbackRepository,
        checkin_repository: CheckinRepository,
        profile_repository: ProfileRepository,
        key_value_repository: Any,
        snapshot_repository: SnapshotRepository,
        utc_now: Callable[[], Any],
        local_date: Callable[[], Any],
        event_buffer: Any,
        competition_repository: CompetitionRepository,
        normalize_profile: Callable[[Any], Any],
        normalize_competition: Callable[[Any], Any],
        uuid_factory: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._activity_feedback_repository = activity_feedback_repository
        self._checkin_repository = checkin_repository
        self._profile_repository = profile_repository
        self._key_value_repository = key_value_repository
        self._snapshot_repository = snapshot_repository
        self._utc_now = utc_now
        self._local_date = local_date
        self._event_buffer = event_buffer
        self._competition_repository = competition_repository
        self._normalize_profile = normalize_profile
        self._normalize_competition = normalize_competition
        self._uuid_factory = uuid_factory

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
            self._database_manager(), self.profile(), self._competition_repository,
            self._normalize_profile, self._normalize_competition,
            self._utc_now, self._uuid_factory,
        )
