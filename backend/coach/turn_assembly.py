from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.final_receipt import CoachFinalReceiptService
from backend.coach.planning_commands import CoachPlanningCommandService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach.structured_turn import (
    CoachStructuredTurnDependencies,
    CoachStructuredTurnService,
)
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.coach.turn_outcome import CoachStructuredOutcomeService


@dataclass(frozen=True)
class TurnPersistence:
    database_manager: Callable[[], Any]
    database_lock: Any
    chat_repository: Any
    key_value_repository: Any
    event_buffer: Any
    utc_now: Callable[[], str]
    uuid_factory: Callable[[], Any]


@dataclass(frozen=True)
class TurnLifecycle:
    root: Any
    logger: Any
    conversation_gate: Any
    maintenance_gate: Any
    receipt_clock: Callable[[], float] = time.time


@dataclass(frozen=True)
class ChatEntryServices:
    settings: Any
    conversation_provision_service: Callable[[], Any]


@dataclass(frozen=True)
class StructuredTurnDialogueServices:
    attachment_context_service: Callable[[], Any]
    dialogue_read_service: Callable[[], Any]
    request_payload_service: Callable[[], Any]
    response_transport: Callable[[], Any]
    tool_round_service: Callable[[], Any]


@dataclass(frozen=True)
class StructuredTurnControlServices:
    tools: Callable[[], list[dict[str, Any]]]
    read_only_tools: Callable[[], Any]
    job_store: Callable[[], Any]
    turn_failure_service: Callable[[], Any]
    tool_dispatch_service: Callable[[], Any]


class CoachTurnAssembly:
    """Compose a structured turn and its session-bound chat entry point."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: TurnPersistence
        lifecycle: TurnLifecycle
        chat_entry: ChatEntryServices
        dialogue: StructuredTurnDialogueServices
        controls: StructuredTurnControlServices

    def __init__(
        self,
        *,
        dependencies: CoachTurnAssembly.Inputs,
    ) -> None:
        persistence = dependencies.persistence
        lifecycle = dependencies.lifecycle
        chat_entry = dependencies.chat_entry
        dialogue = dependencies.dialogue
        controls = dependencies.controls
        self._database_manager = persistence.database_manager
        self._database_lock = persistence.database_lock
        self._chat_repository = persistence.chat_repository
        self._key_value_repository = persistence.key_value_repository
        self._event_buffer = persistence.event_buffer
        self._utc_now = persistence.utc_now
        self._uuid_factory = persistence.uuid_factory
        self._root = lifecycle.root
        self._logger = lifecycle.logger
        self._conversation_gate = lifecycle.conversation_gate
        self._maintenance_gate = lifecycle.maintenance_gate
        self._receipt_clock = lifecycle.receipt_clock
        self._response_retry_policy = CoachResponseRetryPolicy(self._logger)
        self._settings = chat_entry.settings
        self._conversation_provision_service = chat_entry.conversation_provision_service
        self._attachment_context_service = dialogue.attachment_context_service
        self._dialogue_read_service = dialogue.dialogue_read_service
        self._request_payload_service = dialogue.request_payload_service
        self._response_transport = dialogue.response_transport
        self._tool_round_service = dialogue.tool_round_service
        self._tools = controls.tools
        self._read_only_tools = controls.read_only_tools
        self._job_store = controls.job_store
        self._turn_failure_service = controls.turn_failure_service
        self._tool_dispatch_service = controls.tool_dispatch_service

    def command_receipt_service(self) -> CoachCommandReceiptService:
        return CoachCommandReceiptService(
            self._database_manager, self._database_lock, now=self._receipt_clock
        )

    def planning_command_service(self) -> CoachPlanningCommandService:
        return CoachPlanningCommandService(
            self._database_manager(),
            self._database_lock,
            self.command_receipt_service(),
            self._tool_dispatch_service(),
            self._turn_failure_service(),
            self._utc_now,
        )

    def turn_opening_service(self) -> CoachTurnOpeningService:
        return CoachTurnOpeningService(
            self._database_manager(),
            self._database_lock,
            self._chat_repository,
            self.command_receipt_service(),
            self._utc_now,
            self._uuid_factory,
        )

    def outcome_service(self) -> CoachStructuredOutcomeService:
        return CoachStructuredOutcomeService(
            self._database_manager(),
            self._database_lock,
            self._key_value_repository,
            frozenset(self._read_only_tools()),
        )

    def conversation_recovery_service(self) -> CoachConversationRecoveryService:
        return CoachConversationRecoveryService(
            self._database_manager(),
            self._database_lock,
            self._key_value_repository,
            self._job_store(),
            self._logger,
        )

    def response_retry_policy(self) -> CoachResponseRetryPolicy:
        return self._response_retry_policy

    def structured_response_service(self) -> CoachStructuredResponseService:
        return CoachStructuredResponseService(
            self._response_transport(),
            self.conversation_recovery_service(),
            self.response_retry_policy(),
            self._job_store(),
        )

    def final_receipt_service(self) -> CoachFinalReceiptService:
        return CoachFinalReceiptService(
            self._database_manager(),
            self._database_lock,
            self._chat_repository,
            self._key_value_repository,
            self._event_buffer,
            self._utc_now,
        )

    def structured_turn_service(self) -> CoachStructuredTurnService:
        return CoachStructuredTurnService(
            CoachStructuredTurnDependencies(
                opening=self.turn_opening_service(),
                attachments=self._attachment_context_service(),
                dialogue=self._dialogue_read_service(),
                payload=self._request_payload_service(),
                response=self.structured_response_service(),
                rounds=self._tool_round_service(),
                outcome=self.outcome_service(),
                final_receipt=self.final_receipt_service(),
                failure=self._turn_failure_service(),
                tools=self._tools(),
                read_only_tools=frozenset(self._read_only_tools()),
                logger=self._logger,
                root=self._root,
            )
        )

    def chat_turn_service(self) -> CoachChatTurnService:
        return CoachChatTurnService(
            self._database_manager,
            self._database_lock,
            self.command_receipt_service(),
            self._settings,
            self._conversation_provision_service(),
            self.structured_turn_service,
            self._utc_now,
            self._conversation_gate,
            self._maintenance_gate,
        )
