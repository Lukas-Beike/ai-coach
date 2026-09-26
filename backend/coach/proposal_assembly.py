"""Composition for session-bound Coach action proposals."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from backend.activities.duplicate_service import DuplicateActivityService
from backend.coach.proposals import (
    CoachProposalConfirmationService,
    CoachProposalCreationService,
    CoachProposalExecutionService,
    CoachProposalReadService,
)
from backend.db.manager import DatabaseManager
from backend.history.undo_service import HistoryUndoService
from backend.sync.state import SyncStateRepository


class CoachProposalAssembly:
    """Create fresh proposal services over current local and provider owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        sync_state_repository: Callable[[], SyncStateRepository],
        duplicate_activity_service: Callable[[], DuplicateActivityService],
        history_undo_service: Callable[[], HistoryUndoService],
        intervals_client_factory: Callable[[], Any],
        maintenance_gate: Callable[[], Any],
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], uuid.UUID],
    ) -> None:
        self._database_manager = database_manager
        self._sync_state_repository = sync_state_repository
        self._duplicate_activity_service = duplicate_activity_service
        self._history_undo_service = history_undo_service
        self._intervals_client_factory = intervals_client_factory
        self._maintenance_gate = maintenance_gate
        self._now = now
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory

    def read_service(self) -> CoachProposalReadService:
        return CoachProposalReadService(self._database_manager(), now=self._now)

    def creation_service(self) -> CoachProposalCreationService:
        return CoachProposalCreationService(
            self._database_manager(),
            self._sync_state_repository(),
            now=self._now,
            utc_now=self._utc_now,
            uuid_factory=self._uuid_factory,
        )

    def confirmation_service(self) -> CoachProposalConfirmationService:
        return CoachProposalConfirmationService(self._database_manager(), now=self._now)

    def execution_service(self) -> CoachProposalExecutionService:
        return CoachProposalExecutionService(
            self._database_manager(),
            self._duplicate_activity_service(),
            self._history_undo_service(),
            self._intervals_client_factory,
            self._maintenance_gate(),
            now=self._now,
            utc_now=self._utc_now,
        )
