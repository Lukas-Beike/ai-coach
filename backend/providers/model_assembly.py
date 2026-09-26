"""Composition for Coach model transports and transient audio transcription."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.observability import DiagnosticCapture
from backend.providers import audio as audio_provider
from backend.providers import gemini as gemini_provider
from backend.providers.http import JsonHttpClient
from backend.providers import openai as openai_provider
from backend.providers.state import ProviderStateService


class ModelTransportAssembly:
    """Create fresh model adapters over the shared provider transport owners."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        selected_thinking_level: Callable[[], str],
        provider_http_client: Callable[[], JsonHttpClient],
        provider_state_service: Callable[[], ProviderStateService],
        diagnostic_capture: DiagnosticCapture,
        logger: Any,
        app_version: str,
        gemini_base_url: str,
        default_openai_base_url: str,
        openai_responses_path: str,
        json_media_type: str,
        max_audio_bytes: int,
        response_timeout_seconds: int,
        background_poll_seconds: int,
        background_max_seconds: int,
        max_response_bytes: Callable[[], int],
        utc_now: Callable[[], str],
        audio_timeout_seconds: int = 90,
        transcription_model: str = "gpt-transcribe",
        monotonic: Callable[[], float] = time.perf_counter,
        wall_time: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._selected_thinking_level = selected_thinking_level
        self._provider_http_client = provider_http_client
        self._provider_state_service = provider_state_service
        self._diagnostic_capture = diagnostic_capture
        self._logger = logger
        self._app_version = app_version
        self._gemini_base_url = gemini_base_url
        self._default_openai_base_url = default_openai_base_url
        self._openai_responses_path = openai_responses_path
        self._json_media_type = json_media_type
        self._max_audio_bytes = max_audio_bytes
        self._response_timeout_seconds = response_timeout_seconds
        self._background_poll_seconds = background_poll_seconds
        self._background_max_seconds = background_max_seconds
        self._max_response_bytes = max_response_bytes
        self._audio_timeout_seconds = audio_timeout_seconds
        self._transcription_model = transcription_model
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._wait = wait
        self._utc_now = utc_now

    def gemini_json_client(self) -> gemini_provider.GeminiJsonClient:
        config = self._config()
        return gemini_provider.GeminiJsonClient(
            api_key=config.gemini_api_key,
            base_url=self._gemini_base_url,
            response_timeout_seconds=self._response_timeout_seconds,
            http_client=self._provider_http_client(),
            provider_state=self._provider_state_service(),
        )

    def audio_transcription_client(self) -> audio_provider.AudioTranscriptionClient:
        config = self._config()
        return audio_provider.AudioTranscriptionClient(
            max_audio_bytes=self._max_audio_bytes,
            openai_api_key=config.openai_api_key,
            gemini_api_key=config.gemini_api_key,
            openai_base_url=config.openai_base_url,
            default_openai_base_url=self._default_openai_base_url,
            openai_transcription_model=self._transcription_model,
            response_timeout_seconds=self._audio_timeout_seconds,
            http_client=self._provider_http_client(),
            gemini_client=self.gemini_json_client(),
        )

    def gemini_stream_client(self) -> gemini_provider.GeminiStreamClient:
        config = self._config()
        return gemini_provider.GeminiStreamClient(
            api_key=config.gemini_api_key,
            base_url=self._gemini_base_url,
            response_timeout_seconds=self._response_timeout_seconds,
            max_bytes=self._max_response_bytes(),
            app_version=self._app_version,
            json_media_type=self._json_media_type,
            provider_state=self._provider_state_service(),
            logger=self._logger,
            opener=gemini_provider.urlopen,
            monotonic=self._monotonic,
            now=self._utc_now,
        )

    def openai_responses_client(self) -> openai_provider.OpenAIResponsesClient:
        config = self._config()
        return openai_provider.OpenAIResponsesClient(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            default_base_url=self._default_openai_base_url,
            responses_path=self._openai_responses_path,
            response_timeout_seconds=self._response_timeout_seconds,
            background_poll_seconds=self._background_poll_seconds,
            background_max_seconds=self._background_max_seconds,
            thinking_level=self._selected_thinking_level,
            http_client=self._provider_http_client(),
            provider_state=self._provider_state_service(),
            logger=self._logger,
            monotonic=self._wall_time,
            wait=self._wait,
        )

    def openai_stream_client(self) -> openai_provider.OpenAIStreamClient:
        config = self._config()
        return openai_provider.OpenAIStreamClient(
            openai_provider.OpenAIStreamConfig(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                default_base_url=self._default_openai_base_url,
                responses_path=self._openai_responses_path,
                timeout=self._response_timeout_seconds,
                max_bytes=self._max_response_bytes(),
                app_version=self._app_version,
                media_type=self._json_media_type,
            ),
            openai_provider.OpenAIStreamTelemetry(
                self._provider_state_service(),
                self._diagnostic_capture,
                self._logger,
                self._monotonic,
                self._utc_now,
            ),
            self._selected_thinking_level,
            opener=openai_provider.urlopen,
            wait=self._wait,
        )
