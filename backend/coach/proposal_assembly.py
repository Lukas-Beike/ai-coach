"""Composition for session-bound Coach action proposals."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ProposalPersistence:
    database_manager: Callable[[], DatabaseManager]
    sync_state_repository: Callable[[], SyncStateRepository]


@dataclass(frozen=True)
class ProposalExecutionOwners:
    duplicate_activity_service: Callable[[], DuplicateActivityService]
    history_undo_service: Callable[[], HistoryUndoService]
    intervals_client_factory: Callable[[], Any]
    maintenance_gate: Callable[[], Any]
    tool_dispatch_service: Callable[[], Any] | None = None


@dataclass(frozen=True)
class ProposalClock:
    utc_now: Callable[[], str]
    now: Callable[[], float] = time.time
    uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4


class CoachProposalAssembly:
    """Create fresh proposal services over current local and provider owners."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: ProposalPersistence
        execution: ProposalExecutionOwners
        clock: ProposalClock

    def __init__(
        self,
        *,
        dependencies: "CoachProposalAssembly.Inputs",
    ) -> None:
        persistence = dependencies.persistence
        execution = dependencies.execution
        clock = dependencies.clock
        self._database_manager = persistence.database_manager
        self._sync_state_repository = persistence.sync_state_repository
        self._duplicate_activity_service = execution.duplicate_activity_service
        self._history_undo_service = execution.history_undo_service
        self._intervals_client_factory = execution.intervals_client_factory
        self._maintenance_gate = execution.maintenance_gate
        self._tool_dispatch_service = execution.tool_dispatch_service
        self._now = clock.now
        self._utc_now = clock.utc_now
        self._uuid_factory = clock.uuid_factory

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
            tool_dispatch_service=self._tool_dispatch_service,
            now=self._now,
            utc_now=self._utc_now,
        )
