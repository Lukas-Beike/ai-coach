"""Composition for Coach structured tool rounds and their support services."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class StructuredToolRoundRuntime:
    database_manager: Callable[[], Any]
    database_lock: Any
    key_value_repository: Any
    root: Any
    logger: Any


@dataclass(frozen=True)
class StructuredToolRoundContract:
    tool_names: Callable[[], Iterable[str]]
    read_only_tools: Callable[[], Iterable[str]]
    sync_period_defaults: Any
    all_sync_days: int
    limits: Callable[[], CoachStructuredToolRoundLimits]


@dataclass(frozen=True)
class StructuredToolRoundServices:
    clarification_service: Callable[[], Any]
    training_patch_service: Callable[[], Any]
    proposal_creation_service: Callable[[], Any]
    tool_dispatch_service: Callable[[], Any]
    dialogue_action_service: Callable[[], Any]
    planning_authority_service: Callable[[], Any]


@dataclass(frozen=True)
class StructuredToolRoundState:
    sync_state_repository: Callable[[], Any]
    job_store: Callable[[], Any]


@dataclass(frozen=True)
class StructuredToolRoundConversation:
    training_context_service: Callable[[], Any]
    response_service: Callable[[], Any]


class CoachStructuredToolRoundAssembly:
    """Create structured tool services while retaining explicit domain owners."""

    @dataclass(frozen=True)
    class Inputs:
        runtime: StructuredToolRoundRuntime
        contract: StructuredToolRoundContract
        services: StructuredToolRoundServices
        state: StructuredToolRoundState
        conversation: StructuredToolRoundConversation

    def __init__(
        self, *, dependencies: CoachStructuredToolRoundAssembly.Inputs
    ) -> None:
        runtime = dependencies.runtime
        contract = dependencies.contract
        services = dependencies.services
        state = dependencies.state
        conversation = dependencies.conversation
        self._database_manager = runtime.database_manager
        self._database_lock = runtime.database_lock
        self._key_value_repository = runtime.key_value_repository
        self._root = runtime.root
        self._logger = runtime.logger
        self._tool_names = contract.tool_names
        self._read_only_tools = contract.read_only_tools
        self._sync_period_defaults = contract.sync_period_defaults
        self._all_sync_days = contract.all_sync_days
        self._tool_round_limits = contract.limits
        self._clarification_service = services.clarification_service
        self._training_patch_service = services.training_patch_service
        self._proposal_creation_service = services.proposal_creation_service
        self._tool_dispatch_service = services.tool_dispatch_service
        self._dialogue_action_service = services.dialogue_action_service
        self._planning_authority_service = services.planning_authority_service
        self._sync_state_repository = state.sync_state_repository
        self._job_store = state.job_store
        self._training_context_service = conversation.training_context_service
        self._response_service = conversation.response_service

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
            self._database_manager(),
            self._database_lock,
            frozenset(self._read_only_tools()),
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
