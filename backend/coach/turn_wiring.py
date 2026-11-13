"""Build the Coach background-job and turn services (#2102).

Like the other Coach builders, every service reads the live owners from the
application context when it is built. The response retry policy is one
stateless instance per process.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.context import AppContext
from backend.coach import attachments as coach_attachments
from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams
from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.cancellation import CoachCancellationService
from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.final_receipt import CoachFinalReceiptService
from backend.coach.job_store import CoachJobStore
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.morning_completion import MorningCoachJobCompletionService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach.structured_turn import (
    CoachStructuredTurnDependencies,
    CoachStructuredTurnService,
)
from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
)
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
from backend.db.repositories import ChatRepository
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance


@dataclass(frozen=True)
class CoachBackgroundJobServices:
    job_store: Callable[[], CoachJobStore]
    turn_failure_service: Callable[[], CoachTurnFailureService]
    job_submission_service: Callable[[], CoachJobSubmissionService]
    cancellation_service: Callable[[], CoachCancellationService]
    background_job_runner: Callable[[], CoachBackgroundJobRunner]


@dataclass(frozen=True)
class CoachTurnServices:
    command_receipt_service: Callable[[], CoachCommandReceiptService]
    outcome_service: Callable[[], CoachStructuredOutcomeService]
    structured_response_service: Callable[[], CoachStructuredResponseService]
    structured_turn_service: Callable[[], CoachStructuredTurnService]
    chat_turn_service: Callable[[], CoachChatTurnService]


def build_coach_background_jobs(
    ctx: AppContext,
    *,
    chat_repository: ChatRepository,
    root: Path,
    read_only_tools: Collection[str],
    session_auth_service: Callable[[], Any],
) -> CoachBackgroundJobServices:
    """Fresh job, failure, submission and runner services per call."""
    event_buffer = runtime_events.STATE_EVENT_BUFFER
    utc_now = runtime_clock.utc_now
    read_only = frozenset(read_only_tools)

    def job_store() -> CoachJobStore:
        return CoachJobStore(
            ctx.database,
            ctx.database_lock,
            COACH_JOB_WORKER.wake_event,
            runtime_maintenance.MAINTENANCE_GATE,
            utc_now,
        )

    def turn_failure_service() -> CoachTurnFailureService:
        return CoachTurnFailureService(
            CoachTurnFailureDependencies(
                database_manager=ctx.database,
                database_lock=ctx.database_lock,
                chat_repository=chat_repository,
                key_values=ctx.key_values,
                event_buffer=event_buffer,
                redactor=ctx.redactor,
                utc_now=utc_now,
                repository_root=root,
                read_only_tools=read_only,
            )
        )

    def job_submission_service() -> CoachJobSubmissionService:
        return CoachJobSubmissionService(
            ctx.database,
            chat_repository,
            ctx.database_lock,
            ctx.settings,
            event_buffer,
            coach_streams.CHAT_STREAM_REGISTRY,
            COACH_JOB_WORKER.wake_event,
            utc_now,
            background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
            max_attachment_storage_bytes=coach_attachments.MAX_ATTACHMENT_STORAGE_BYTES,
        )

    def cancellation_service() -> CoachCancellationService:
        return CoachCancellationService(
            job_submission_service(), job_store(), coach_streams.CHAT_STREAM_REGISTRY
        )

    def morning_completion_service() -> MorningCoachJobCompletionService:
        return MorningCoachJobCompletionService(
            ctx.database(),
            ctx.database_lock,
            ctx.key_values,
            ctx.coach_local.quick_actions_service,
            ctx.clock.now,
            utc_now,
        )

    def background_job_runner() -> CoachBackgroundJobRunner:
        return CoachBackgroundJobRunner(
            job_store(),
            lambda: ctx.coach_turns.chat_turn_service(),
            session_auth_service,
            coach_streams.CHAT_STREAM_REGISTRY,
            ctx.coach_local.manual_morning_checkin_service,
            morning_completion_service,
            turn_failure_service,
            runtime_maintenance.MAINTENANCE_GATE,
            ctx.redactor,
            ctx.logger,
        )

    return CoachBackgroundJobServices(
        job_store,
        turn_failure_service,
        job_submission_service,
        cancellation_service,
        background_job_runner,
    )


def build_coach_turns(
    ctx: AppContext,
    *,
    chat_repository: ChatRepository,
    conversation_gate: Any,
    root: Path,
    read_only_tools: Collection[str],
) -> CoachTurnServices:
    """Fresh structured turns and the session-bound chat entry point per call."""
    event_buffer = runtime_events.STATE_EVENT_BUFFER
    utc_now = runtime_clock.utc_now
    receipt_clock = time.time
    maintenance_gate = runtime_maintenance.MAINTENANCE_GATE
    read_only = frozenset(read_only_tools)
    retry_policy = CoachResponseRetryPolicy(ctx.logger)

    def command_receipt_service() -> CoachCommandReceiptService:
        return CoachCommandReceiptService(ctx.database, now=receipt_clock)

    def outcome_service() -> CoachStructuredOutcomeService:
        return CoachStructuredOutcomeService(
            ctx.database(), ctx.database_lock, ctx.key_values, read_only
        )

    def structured_response_service() -> CoachStructuredResponseService:
        return CoachStructuredResponseService(
            ctx.coach_conversation.response_transport(),
            CoachConversationRecoveryService(
                ctx.database(), ctx.database_lock, ctx.key_values, ctx.logger
            ),
            retry_policy,
            ctx.coach_background_jobs.job_store(),
        )

    def structured_turn_service() -> CoachStructuredTurnService:
        conversation = ctx.coach_conversation
        return CoachStructuredTurnService(
            CoachStructuredTurnDependencies(
                opening=CoachTurnOpeningService(
                    ctx.database(),
                    ctx.database_lock,
                    chat_repository,
                    command_receipt_service(),
                    utc_now,
                    uuid.uuid4,
                ),
                attachments=conversation.attachment_context_service(),
                conversations=conversation.provision_service(),
                dialogue=conversation.dialogue_read_service(),
                payload=ctx.coach_context.request_payload_service(),
                response=structured_response_service(),
                rounds=ctx.coach_tool_rounds.service(),
                outcome=outcome_service(),
                final_receipt=CoachFinalReceiptService(
                    ctx.database(),
                    ctx.database_lock,
                    chat_repository,
                    ctx.key_values,
                    event_buffer,
                    utc_now,
                ),
                failure=ctx.coach_background_jobs.turn_failure_service(),
                tools=ctx.coach_dialogue_tools,
                read_only_tools=read_only,
                logger=ctx.logger,
                root=root,
            )
        )

    def chat_turn_service() -> CoachChatTurnService:
        return CoachChatTurnService(
            ctx.database,
            ctx.database_lock,
            command_receipt_service(),
            ctx.settings,
            ctx.coach_conversation.provision_service,
            structured_turn_service,
            utc_now,
            conversation_gate,
            maintenance_gate,
        )

    return CoachTurnServices(
        command_receipt_service,
        outcome_service,
        structured_response_service,
        structured_turn_service,
        chat_turn_service,
    )
