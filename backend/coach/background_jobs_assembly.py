from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.cancellation import CoachCancellationService
from backend.coach.job_store import CoachJobStore
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.morning_completion import MorningCoachJobCompletionService
from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
)


class CoachBackgroundJobsAssembly:
    """Compose the shared persistence, command, and runner services for Coach jobs."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        database_lock: Any,
        worker_wake_event: Callable[[], Any],
        maintenance_gate: Callable[[], Any],
        utc_now: Callable[[], str],
        chat_repository: Any,
        key_value_repository: Any,
        event_buffer: Any,
        redactor: Any,
        repository_root: Any,
        logger: Any,
        read_only_tools: Callable[[], Any],
        settings: Any,
        stream_registry: Callable[[], Any],
        session_auth_service: Callable[[], Any],
        chat_turn_service: Callable[[], Any],
        manual_morning_checkin_service: Callable[[], Any],
        quick_actions_service: Callable[[], Any],
        athlete_clock: Callable[[], Any],
        background_horizon_days: Callable[[], int],
        max_attachment_storage_bytes: Callable[[], int],
        max_gemini_inline_image_bytes: Callable[[], int],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._worker_wake_event = worker_wake_event
        self._maintenance_gate = maintenance_gate
        self._utc_now = utc_now
        self._chat_repository = chat_repository
        self._key_value_repository = key_value_repository
        self._event_buffer = event_buffer
        self._redactor = redactor
        self._repository_root = repository_root
        self._logger = logger
        self._read_only_tools = read_only_tools
        self._settings = settings
        self._stream_registry = stream_registry
        self._session_auth_service = session_auth_service
        self._chat_turn_service = chat_turn_service
        self._manual_morning_checkin_service = manual_morning_checkin_service
        self._quick_actions_service = quick_actions_service
        self._athlete_clock = athlete_clock
        self._background_horizon_days = background_horizon_days
        self._max_attachment_storage_bytes = max_attachment_storage_bytes
        self._max_gemini_inline_image_bytes = max_gemini_inline_image_bytes

    def job_store(self) -> CoachJobStore:
        return CoachJobStore(
            self._database_manager,
            self._database_lock,
            self._worker_wake_event(),
            self._maintenance_gate(),
            self._utc_now,
        )

    def turn_failure_service(self) -> CoachTurnFailureService:
        return CoachTurnFailureService(CoachTurnFailureDependencies(
            database_manager=self._database_manager,
            database_lock=self._database_lock,
            chat_repository=self._chat_repository,
            key_values=self._key_value_repository,
            event_buffer=self._event_buffer,
            redactor=self._redactor,
            utc_now=self._utc_now,
            repository_root=self._repository_root,
            read_only_tools=frozenset(self._read_only_tools()),
        ))

    def job_submission_service(self) -> CoachJobSubmissionService:
        return CoachJobSubmissionService(
            self._database_manager,
            self._chat_repository,
            self._database_lock,
            self._settings,
            self._event_buffer,
            self._stream_registry(),
            self._worker_wake_event(),
            self._utc_now,
            background_horizon_days=self._background_horizon_days(),
            max_attachment_storage_bytes=self._max_attachment_storage_bytes(),
            max_gemini_inline_image_bytes=self._max_gemini_inline_image_bytes(),
        )

    def cancellation_service(self) -> CoachCancellationService:
        return CoachCancellationService(
            self.job_submission_service(), self.job_store(), self._stream_registry()
        )

    def morning_completion_service(self) -> MorningCoachJobCompletionService:
        return MorningCoachJobCompletionService(
            self._database_manager(),
            self._database_lock,
            self._key_value_repository,
            self._quick_actions_service,
            self._athlete_clock(),
            self._utc_now,
        )

    def background_job_runner(self) -> CoachBackgroundJobRunner:
        return CoachBackgroundJobRunner(
            self.job_store(),
            self._chat_turn_service,
            self._session_auth_service,
            self._stream_registry(),
            self._manual_morning_checkin_service,
            self.morning_completion_service,
            self.turn_failure_service,
            self._maintenance_gate(),
            self._redactor,
            self._logger,
        )
