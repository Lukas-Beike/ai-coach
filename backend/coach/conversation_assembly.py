"""Composition for durable Coach conversation state and local history."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from backend.coach.attachments import MAX_GEMINI_INLINE_IMAGE_BYTES
from backend.coach.conversation import (
    CoachConversationHistoryService,
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
    GeminiConversationHistoryService,
    GeminiLocalChatHistoryService,
)
from backend.coach.streams import ChatStreamRegistry
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.providers.openai import OpenAIResponsesClient
from backend.runtime.events import StateEventBuffer
from backend.settings import SettingsService


class CoachConversationAssembly:
    """Create fresh conversation services over shared application state."""

    def __init__(
        self,
        *,
        settings: SettingsService,
        database_manager: Callable[[], DatabaseManager],
        key_values: KeyValueRepository,
        chat_repository: ChatRepository,
        state_event_buffer: StateEventBuffer,
        database_lock: Any,
        streams: ChatStreamRegistry,
        conversation_lock: Any,
        openai_client: Callable[[], OpenAIResponsesClient],
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], uuid.UUID],
        logger: Any,
        max_gemini_inline_image_bytes: Callable[[], int] | None = None,
    ) -> None:
        self._settings = settings
        self._database_manager = database_manager
        self._key_values = key_values
        self._chat_repository = chat_repository
        self._state_event_buffer = state_event_buffer
        self._database_lock = database_lock
        self._streams = streams
        self._conversation_lock = conversation_lock
        self._openai_client = openai_client
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._logger = logger
        self._max_gemini_inline_image_bytes = (
            max_gemini_inline_image_bytes
            or (lambda: MAX_GEMINI_INLINE_IMAGE_BYTES)
        )

    def provision_service(self) -> CoachConversationProvisionService:
        return CoachConversationProvisionService(
            self._settings,
            self._database_manager(),
            self._key_values,
            self._openai_client(),
            self._database_lock,
            self._uuid_factory,
        )

    def reset_service(self) -> CoachConversationResetService:
        return CoachConversationResetService(
            self._database_manager(),
            self._key_values,
            self._openai_client(),
            self._streams,
            self._database_lock,
            self._conversation_lock,
            self._utc_now,
            self._uuid_factory,
            self._logger,
        )

    def gemini_history_service(self) -> GeminiConversationHistoryService:
        return GeminiConversationHistoryService(self._database_manager(), self._key_values)

    def message_service(self) -> CoachMessageService:
        return CoachMessageService(
            self._database_manager(), self._chat_repository, self._state_event_buffer
        )

    def history_service(self) -> CoachConversationHistoryService:
        return CoachConversationHistoryService(
            self._database_manager(),
            self._chat_repository,
            self._key_values,
            self._database_lock,
        )

    def gemini_local_history_service(self) -> GeminiLocalChatHistoryService:
        return GeminiLocalChatHistoryService(
            self._database_manager(),
            self._chat_repository,
            max_inline_bytes=self._max_gemini_inline_image_bytes(),
        )
