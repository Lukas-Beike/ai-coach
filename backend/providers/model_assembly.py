"""Composition for model transports and transient audio transcription.

The selected model names its provider: a Claude family goes to the Anthropic
Messages API, anything else to OpenAI Responses. There is no fallback from one
provider to the other; voice transcription always uses OpenAI.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from backend.config import DEFAULT_ANTHROPIC_BASE_URL, Config
from backend.observability import DiagnosticCapture
from backend.providers import audio as audio_provider
from backend.providers import http as provider_http
from backend.providers import openai_requests, openai_responses_adapter, openai_stream
from backend.providers.claude_models import ClaudeModelResolver, setting_family
from backend.providers.claude_requests import (
    ClaudeMessagesClient,
    ClaudeTransportConfig,
)
from backend.providers.http import JsonHttpClient
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.openai_requests import ResponsesClock
from backend.providers.state import ProviderStateService

# Where the newest, working and rejected Claude model per family are kept.
CLAUDE_MODELS_KEY = "claude_models"


@dataclass(frozen=True)
class ModelProviderOwners:
    config: Callable[[], Config]
    selected_thinking_level: Callable[[], str]
    http_client: Callable[[], JsonHttpClient]
    state_service: Callable[[], ProviderStateService]
    service_tier: Callable[[str], str | None] = lambda model: None
    # Key/value access for the Claude model state.
    read_value: Callable[[str], str | None] = lambda key: None
    write_value: Callable[[str, str], None] = lambda key, value: None


@dataclass(frozen=True)
class ModelEndpointSettings:
    default_openai_base_url: str
    openai_responses_path: str
    json_media_type: str
    # Longest silence in a streamed response; a plain request has its own limit.
    response_timeout_seconds: int
    request_timeout_seconds: int
    default_anthropic_base_url: str = DEFAULT_ANTHROPIC_BASE_URL


@dataclass(frozen=True)
class AudioTranscriptionSettings:
    max_audio_bytes: int
    timeout_seconds: int = 90
    model: str = "gpt-transcribe"


@dataclass(frozen=True)
class ModelProviderDiagnostics:
    diagnostic_capture: DiagnosticCapture
    logger: Any
    app_version: str


@dataclass(frozen=True)
class ModelResponseLimits:
    max_response_bytes: Callable[[], int]


@dataclass(frozen=True)
class ModelTransportClock:
    utc_now: Callable[[], str]
    monotonic: Callable[[], float] = time.perf_counter
    wait: Callable[[float], None] = time.sleep


class ModelTransportAssembly:
    """Create fresh model adapters over the shared provider transport owners."""

    @dataclass(frozen=True)
    class Inputs:
        providers: ModelProviderOwners
        endpoints: ModelEndpointSettings
        audio: AudioTranscriptionSettings
        diagnostics: ModelProviderDiagnostics
        limits: ModelResponseLimits
        clock: ModelTransportClock

    def __init__(self, *, dependencies: ModelTransportAssembly.Inputs) -> None:
        providers = dependencies.providers
        endpoints = dependencies.endpoints
        audio = dependencies.audio
        diagnostics = dependencies.diagnostics
        limits = dependencies.limits
        clock = dependencies.clock
        self._service_tier = providers.service_tier
        self._config = providers.config
        self._selected_thinking_level = providers.selected_thinking_level
        self._provider_http_client = providers.http_client
        self._provider_state_service = providers.state_service
        self._diagnostic_capture = diagnostics.diagnostic_capture
        self._logger = diagnostics.logger
        self._app_version = diagnostics.app_version
        self._default_openai_base_url = endpoints.default_openai_base_url
        self._openai_responses_path = endpoints.openai_responses_path
        self._json_media_type = endpoints.json_media_type
        self._max_audio_bytes = audio.max_audio_bytes
        self._response_timeout_seconds = endpoints.response_timeout_seconds
        self._request_timeout_seconds = endpoints.request_timeout_seconds
        self._max_response_bytes = limits.max_response_bytes
        self._audio_timeout_seconds = audio.timeout_seconds
        self._transcription_model = audio.model
        self._monotonic = clock.monotonic
        self._wait = clock.wait
        self._utc_now = clock.utc_now
        self._default_anthropic_base_url = endpoints.default_anthropic_base_url
        self._read_value = providers.read_value
        self._write_value = providers.write_value
        # One resolver: it serializes the stored model state.
        self._claude_models = ClaudeModelResolver(
            read_state=self._read_claude_models,
            write_state=lambda state: self._write_value(
                CLAUDE_MODELS_KEY, json.dumps(state, sort_keys=True)
            ),
            list_models=lambda: self.claude_client().list_models(),
            now=lambda: datetime.now(UTC),
            logger=self._logger,
        )

    def _read_claude_models(self) -> Any:
        try:
            return json.loads(self._read_value(CLAUDE_MODELS_KEY) or "{}")
        except ValueError:
            return {}

    def claude_models(self) -> ClaudeModelResolver:
        return self._claude_models

    def claude_client(self) -> ClaudeMessagesClient:
        config = self._config()
        return ClaudeMessagesClient(
            ClaudeTransportConfig(
                api_key=config.anthropic_api_key,
                base_url=config.anthropic_base_url,
                default_base_url=self._default_anthropic_base_url,
                timeout_seconds=self._response_timeout_seconds,
                max_response_bytes=self._max_response_bytes(),
                app_version=self._app_version,
            ),
            provider_state=self._provider_state_service(),
            logger=self._logger,
            opener=provider_http.urlopen,
            clock=self._monotonic,
        )

    def complete(self, request: ModelRequest) -> ModelTurn:
        """A one-shot answer from the provider the model names."""
        family = setting_family(request.model)
        if family is None:
            return self.openai_responses_client().complete(request)
        client = self.claude_client()
        return self._claude_models.call(
            family, lambda model: client.complete(replace(request, model=model))
        )

    def stream(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: Any = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        """A streamed answer from the provider the model names."""
        family = setting_family(request.model)
        if family is None:
            return openai_responses_adapter.model_turn(
                self.openai_stream_client().stream(
                    openai_responses_adapter.request_payload(request),
                    on_text_delta,
                    cancel_event=cancel_event,
                    on_response_id=on_response_id,
                )
            )
        client = self.claude_client()
        return self._claude_models.call(
            family,
            lambda model: client.stream(
                replace(request, model=model),
                on_text_delta,
                cancel_event,
                on_response_id,
            ),
        )

    def audio_transcription_client(self) -> audio_provider.AudioTranscriptionClient:
        config = self._config()
        return audio_provider.AudioTranscriptionClient(
            max_audio_bytes=self._max_audio_bytes,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            default_openai_base_url=self._default_openai_base_url,
            openai_transcription_model=self._transcription_model,
            response_timeout_seconds=self._audio_timeout_seconds,
            http_client=self._provider_http_client(),
            provider_state=self._provider_state_service(),
        )

    def openai_responses_client(self) -> openai_requests.OpenAIResponsesClient:
        config = self._config()
        return openai_requests.OpenAIResponsesClient(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            default_base_url=self._default_openai_base_url,
            responses_path=self._openai_responses_path,
            response_timeout_seconds=self._request_timeout_seconds,
            thinking_level=self._selected_thinking_level,
            http_client=self._provider_http_client(),
            provider_state=self._provider_state_service(),
            logger=self._logger,
            clock=ResponsesClock(self._wait),
            service_tier=self._service_tier,
        )

    def openai_stream_client(self) -> openai_stream.OpenAIStreamClient:
        config = self._config()
        return openai_stream.OpenAIStreamClient(
            openai_stream.OpenAIStreamConfig(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                default_base_url=self._default_openai_base_url,
                responses_path=self._openai_responses_path,
                timeout=self._response_timeout_seconds,
                max_bytes=self._max_response_bytes(),
                app_version=self._app_version,
                media_type=self._json_media_type,
            ),
            openai_stream.OpenAIStreamTelemetry(
                self._provider_state_service(),
                self._diagnostic_capture,
                self._logger,
                self._monotonic,
                self._utc_now,
            ),
            self._selected_thinking_level,
            opener=provider_http.urlopen,
            wait=self._wait,
            service_tier=self._service_tier,
        )
