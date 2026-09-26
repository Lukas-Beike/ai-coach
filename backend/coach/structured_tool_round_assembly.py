"""Composition for Coach structured tool rounds and their support services."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
    CoachStructuredToolRoundService,
)
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal


class CoachStructuredToolRoundAssembly:
    """Create structured tool services while retaining explicit domain owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        database_lock: Any,
        key_value_repository: Any,
        root: Any,
        logger: Any,
        tool_names: Callable[[], Iterable[str]],
        read_only_tools: Callable[[], Iterable[str]],
        sync_period_defaults: Any,
        all_sync_days: int,
        clarification_service: Callable[[], Any],
        training_patch_service: Callable[[], Any],
        sync_state_repository: Callable[[], Any],
        proposal_creation_service: Callable[[], Any],
        tool_dispatch_service: Callable[[], Any],
        job_store: Callable[[], Any],
        dialogue_action_service: Callable[[], Any],
        planning_authority_service: Callable[[], Any],
        training_context_service: Callable[[], Any],
        response_service: Callable[[], Any],
        tool_round_limits: Callable[[], CoachStructuredToolRoundLimits],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_value_repository = key_value_repository
        self._root = root
        self._logger = logger
        self._tool_names = tool_names
        self._read_only_tools = read_only_tools
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._clarification_service = clarification_service
        self._training_patch_service = training_patch_service
        self._sync_state_repository = sync_state_repository
        self._proposal_creation_service = proposal_creation_service
        self._tool_dispatch_service = tool_dispatch_service
        self._job_store = job_store
        self._dialogue_action_service = dialogue_action_service
        self._planning_authority_service = planning_authority_service
        self._training_context_service = training_context_service
        self._response_service = response_service
        self._tool_round_limits = tool_round_limits

    def execution_service(self) -> CoachStructuredToolExecutionService:
        return CoachStructuredToolExecutionService(
            self._database_manager(),
            self._database_lock,
            self._key_value_repository,
            self._clarification_service(),
            self._training_patch_service(),
            self._sync_state_repository(),
            self._proposal_creation_service(),
            self._tool_dispatch_service(),
        )

    def failure_service(self) -> CoachStructuredToolFailureService:
        return CoachStructuredToolFailureService(
            self._root, self._logger, frozenset(self._tool_names())
        )

    def round_journal(self) -> CoachStructuredToolRoundJournal:
        return CoachStructuredToolRoundJournal(self._job_store())

    def replay_service(self) -> CoachStructuredToolReplayService:
        return CoachStructuredToolReplayService(
            self._database_manager(), self._database_lock, frozenset(self._read_only_tools())
        )

    def preparation_service(self) -> CoachStructuredToolPreparationService:
        return CoachStructuredToolPreparationService(
            self._dialogue_action_service(),
            self._sync_state_repository(),
            self._planning_authority_service(),
            frozenset(self._read_only_tools()),
            self._sync_period_defaults,
            self._all_sync_days,
        )

    def service(self) -> CoachStructuredToolRoundService:
        return CoachStructuredToolRoundService(
            self._database_manager,
            self._database_lock,
            self.replay_service(),
            self.preparation_service(),
            self.execution_service(),
            self.failure_service(),
            self.round_journal(),
            self._job_store(),
            self._training_context_service(),
            self._response_service(),
            self._tool_round_limits(),
        )
