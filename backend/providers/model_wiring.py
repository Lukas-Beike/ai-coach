"""Build the model transports and transient audio transcription.

The selected model names its provider: a Claude family goes to the Anthropic
Messages API, anything else to OpenAI Responses. There is no fallback from one
provider to the other. Voice transcription uses OpenAI unless a separate
OpenAI-compatible transcription endpoint is configured.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from backend.config import DEFAULT_ANTHROPIC_BASE_URL, DEFAULT_OPENAI_BASE_URL, Config
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
from backend.runtime import clock as runtime_clock

# Where the newest, working and rejected Claude model per family are kept.
CLAUDE_MODELS_KEY = "claude_models"

# Voice transcription: the model and how long one request may take.
TRANSCRIPTION_MODEL = "gpt-transcribe"
TRANSCRIPTION_TIMEOUT_SECONDS = 90


JSON_MEDIA_TYPE = "application/json"
OPENAI_RESPONSES_PATH = "/responses"
# The longest silence allowed between two parts of a streamed model response.
# Long reasoning on a large plan may send nothing for minutes (athlete
# decision 2026-11-11, #2073: 10 minutes instead of 3).
OPENAI_RESPONSE_TIMEOUT_SECONDS = 600
# Plain OpenAI requests (impact classifier, remote conversation create/delete).
OPENAI_REQUEST_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class ModelTransportServices:
    claude_models: Callable[[], ClaudeModelResolver]
    claude_client: Callable[[], ClaudeMessagesClient]
    # complete(request) and stream(request, on_text_delta, cancel_event=None,
    # on_response_id=None) route by the provider the model names.
    complete: Callable[[ModelRequest], ModelTurn]
    stream: Callable[..., ModelTurn]
    audio_transcription_client: Callable[[], audio_provider.AudioTranscriptionClient]
    openai_responses_client: Callable[[], openai_requests.OpenAIResponsesClient]
    openai_stream_client: Callable[[], openai_stream.OpenAIStreamClient]


def build_model_transport(
    *,
    config: Callable[[], Config],
    selected_thinking_level: Callable[[], str],
    service_tier: Callable[[str], str | None],
    http_client: Callable[[], JsonHttpClient],
    provider_state: Callable[[], ProviderStateService],
    read_value: Callable[[str], str | None],
    write_value: Callable[[str, str], None],
    logger: Any,
    diagnostic_capture: DiagnosticCapture,
    app_version: str,
    max_audio_bytes: int,
) -> ModelTransportServices:
    """Fresh model adapters per call over the shared provider transport owners."""
    monotonic = time.perf_counter
    wait = time.sleep
    utc_now = runtime_clock.utc_now

    def max_response_bytes() -> int:
        return provider_http.MAX_EXTERNAL_RESPONSE_BYTES

    def read_claude_models() -> Any:
        try:
            return json.loads(read_value(CLAUDE_MODELS_KEY) or "{}")
        except ValueError:
            return {}

    # One resolver: it serializes the stored model state.
    claude_resolver = ClaudeModelResolver(
        read_state=read_claude_models,
        write_state=lambda state: write_value(
            CLAUDE_MODELS_KEY, json.dumps(state, sort_keys=True)
        ),
        list_models=lambda: claude_client().list_models(),
        now=lambda: datetime.now(UTC),
        logger=logger,
    )

    def claude_models() -> ClaudeModelResolver:
        return claude_resolver

    def claude_client() -> ClaudeMessagesClient:
        active = config()
        return ClaudeMessagesClient(
            ClaudeTransportConfig(
                api_key=active.anthropic_api_key,
                base_url=active.anthropic_base_url,
                default_base_url=DEFAULT_ANTHROPIC_BASE_URL,
                timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
                max_response_bytes=max_response_bytes(),
                app_version=app_version,
            ),
            provider_state=provider_state(),
            logger=logger,
            opener=provider_http.urlopen,
            clock=monotonic,
            diagnostic_capture=diagnostic_capture,
        )

    def openai_responses_client() -> openai_requests.OpenAIResponsesClient:
        active = config()
        return openai_requests.OpenAIResponsesClient(
            api_key=active.openai_api_key,
            base_url=active.openai_base_url,
            default_base_url=DEFAULT_OPENAI_BASE_URL,
            responses_path=OPENAI_RESPONSES_PATH,
            response_timeout_seconds=OPENAI_REQUEST_TIMEOUT_SECONDS,
            thinking_level=selected_thinking_level,
            http_client=http_client(),
            provider_state=provider_state(),
            logger=logger,
            clock=ResponsesClock(wait),
            service_tier=service_tier,
        )

    def openai_stream_client() -> openai_stream.OpenAIStreamClient:
        active = config()
        return openai_stream.OpenAIStreamClient(
            openai_stream.OpenAIStreamConfig(
                api_key=active.openai_api_key,
                base_url=active.openai_base_url,
                default_base_url=DEFAULT_OPENAI_BASE_URL,
                responses_path=OPENAI_RESPONSES_PATH,
                timeout=OPENAI_RESPONSE_TIMEOUT_SECONDS,
                max_bytes=max_response_bytes(),
                app_version=app_version,
                media_type=JSON_MEDIA_TYPE,
            ),
            openai_stream.OpenAIStreamTelemetry(
                provider_state(), diagnostic_capture, logger, monotonic, utc_now
            ),
            selected_thinking_level,
            opener=provider_http.urlopen,
            wait=wait,
            service_tier=service_tier,
        )

    def audio_transcription_client() -> audio_provider.AudioTranscriptionClient:
        active = config()
        local = bool(active.transcription_base_url)
        return audio_provider.AudioTranscriptionClient(
            max_audio_bytes=max_audio_bytes,
            # A local server never receives the OpenAI key.
            api_key=active.transcription_api_key if local else active.openai_api_key,
            base_url=active.transcription_base_url or active.openai_base_url,
            default_base_url=DEFAULT_OPENAI_BASE_URL,
            model=active.transcription_model or TRANSCRIPTION_MODEL,
            response_timeout_seconds=TRANSCRIPTION_TIMEOUT_SECONDS,
            http_client=http_client(),
            provider_state=provider_state(),
            local_endpoint=local,
        )

    def complete(request: ModelRequest) -> ModelTurn:
        """A one-shot answer from the provider the model names."""
        family = setting_family(request.model)
        if family is None:
            return openai_responses_client().complete(request)
        client = claude_client()
        return claude_resolver.call(
            family, lambda model: client.complete(replace(request, model=model))
        )

    def stream(
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: Any = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        """A streamed answer from the provider the model names."""
        family = setting_family(request.model)
        if family is None:
            return openai_responses_adapter.model_turn(
                openai_stream_client().stream(
                    openai_responses_adapter.request_payload(request),
                    on_text_delta,
                    cancel_event=cancel_event,
                    on_response_id=on_response_id,
                )
            )
        client = claude_client()
        return claude_resolver.call(
            family,
            lambda model: client.stream(
                replace(request, model=model),
                on_text_delta,
                cancel_event,
                on_response_id,
            ),
        )

    return ModelTransportServices(
        claude_models,
        claude_client,
        complete,
        stream,
        audio_transcription_client,
        openai_responses_client,
        openai_stream_client,
    )
