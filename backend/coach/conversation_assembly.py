"""Composition for durable Coach conversation state and local history."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.coach.attachments import MAX_GEMINI_INLINE_IMAGE_BYTES
from backend.coach.conversation import (
    CoachAttachmentContextService,
    CoachConversationHistoryService,
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
    GeminiConversationHistoryService,
    GeminiConversationResponseService,
    GeminiLocalChatHistoryService,
    GeminiRequestPayloadService,
    GeminiResponseNormalizationService,
)
from backend.coach.dialogue import CoachDialogueReadService
from backend.coach.response_transport import CoachResponseTransport
from backend.coach.streams import ChatStreamRegistry
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.providers.openai import OpenAIResponsesClient
from backend.runtime.events import StateEventBuffer
from backend.settings import SettingsService


@dataclass(frozen=True)
class ConversationPersistence:
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    chat_repository: ChatRepository
    state_event_buffer: StateEventBuffer
    database_lock: Any


@dataclass(frozen=True)
class ConversationRuntime:
    streams: ChatStreamRegistry
    conversation_lock: Any
    openai_client: Callable[[], OpenAIResponsesClient]
    utc_now: Callable[[], str]
    uuid_factory: Callable[[], uuid.UUID]
    logger: Any


@dataclass(frozen=True)
class ConversationProfile:
    profile_service: Callable[[], Any]


@dataclass(frozen=True)
class ConversationModelDependencies:
    settings: SettingsService
    model_transport: Any
    default_thinking_level: Callable[[], Any]
    default_max_output_tokens: int
    json_media_type: str
    max_gemini_inline_image_bytes: Callable[[], int] | None = None


class CoachConversationAssembly:
    """Create fresh conversation services over shared application state."""

    def __init__(
        self,
        *,
        persistence: ConversationPersistence,
        runtime: ConversationRuntime,
        profile: ConversationProfile,
        model: ConversationModelDependencies,
    ) -> None:
        self._settings = model.settings
        self._database_manager = persistence.database_manager
        self._key_values = persistence.key_values
        self._chat_repository = persistence.chat_repository
        self._state_event_buffer = persistence.state_event_buffer
        self._database_lock = persistence.database_lock
        self._streams = runtime.streams
        self._conversation_lock = runtime.conversation_lock
        self._openai_client = runtime.openai_client
        self._utc_now = runtime.utc_now
        self._uuid_factory = runtime.uuid_factory
        self._logger = runtime.logger
        self._profile_service = profile.profile_service
        self._model_transport = model.model_transport
        self._default_thinking_level = model.default_thinking_level
        self._default_max_output_tokens = model.default_max_output_tokens
        self._json_media_type = model.json_media_type
        self._max_gemini_inline_image_bytes = model.max_gemini_inline_image_bytes or (
            lambda: MAX_GEMINI_INLINE_IMAGE_BYTES
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
        return GeminiConversationHistoryService(
            self._database_manager(), self._key_values
        )

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

    def dialogue_read_service(self) -> CoachDialogueReadService:
        manager = self._database_manager()
        return CoachDialogueReadService(
            manager,
            self.message_service(),
            self._key_values,
            self._profile_service(),
        )

    def attachment_context_service(self) -> CoachAttachmentContextService:
        return CoachAttachmentContextService(self._database_manager())

    def gemini_request_payload_service(self) -> GeminiRequestPayloadService:
        return GeminiRequestPayloadService(
            self.gemini_history_service(),
            self.gemini_local_history_service(),
            self._database_manager(),
            self._key_values,
        )

    def gemini_response_normalization_service(
        self,
    ) -> GeminiResponseNormalizationService:
        return GeminiResponseNormalizationService(
            self.gemini_history_service(),
            self._database_manager(),
            self._key_values,
            self._uuid_factory,
        )

    def gemini_conversation_response_service(self) -> GeminiConversationResponseService:
        return GeminiConversationResponseService(
            self.gemini_request_payload_service(),
            self.gemini_response_normalization_service(),
            self._model_transport.gemini_json_client(),
            self._model_transport.gemini_stream_client(),
            settings_service=self._settings,
            default_thinking_level=self._default_thinking_level(),
            default_max_output_tokens=self._default_max_output_tokens,
            json_media_type=self._json_media_type,
        )

    def response_transport(self) -> CoachResponseTransport:
        return CoachResponseTransport(
            self._settings,
            self._model_transport.openai_responses_client,
            self._model_transport.openai_stream_client,
            self.gemini_conversation_response_service,
        )
