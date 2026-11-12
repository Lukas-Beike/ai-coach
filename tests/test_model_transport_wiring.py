from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.providers import audio as audio_provider
from backend.providers import http as provider_http
from backend.providers import (
    model_wiring,
    openai_requests,
    openai_responses_adapter,
    openai_stream,
)
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.model_wiring import CLAUDE_MODELS_KEY, build_model_transport


class ModelTransportWiringTests(unittest.TestCase):
    def make_services(self):
        config = SimpleNamespace(
            openai_api_key="openai-test-key",
            openai_base_url="https://openai.example.invalid/v1",
            anthropic_api_key="anthropic-test-key",
            anthropic_base_url="https://claude.example.invalid",
        )
        self.values = {}
        self.thinking = Mock(return_value="high")
        self.config = Mock(return_value=config)
        self.http = Mock(return_value=Mock(name="provider_http_client"))
        self.state = Mock(return_value=Mock(name="provider_state"))
        return build_model_transport(
            config=self.config,
            selected_thinking_level=self.thinking,
            service_tier=Mock(return_value=None),
            http_client=self.http,
            provider_state=self.state,
            read_value=self.values.get,
            write_value=self.values.__setitem__,
            logger=Mock(name="logger"),
            diagnostic_capture=Mock(name="diagnostics"),
            app_version="test-version",
            max_audio_bytes=2048,
        )

    def test_building_resolves_no_owner(self):
        self.make_services()
        for owner in (self.config, self.thinking, self.http, self.state):
            owner.assert_not_called()

    def test_openai_adapter_resolves_active_config_and_shared_owners_per_call(self):
        services = self.make_services()
        with patch.object(
            openai_requests, "OpenAIResponsesClient", return_value="client"
        ) as factory:
            self.assertEqual(services.openai_responses_client(), "client")

        self.config.assert_called_once()
        self.thinking.assert_not_called()
        self.http.assert_called_once()
        self.state.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["api_key"], "openai-test-key")
        self.assertIs(factory.call_args.kwargs["thinking_level"], self.thinking)
        self.assertIs(factory.call_args.kwargs["http_client"], self.http.return_value)
        # A plain request keeps its own limit, apart from the streamed one.
        self.assertEqual(factory.call_args.kwargs["response_timeout_seconds"], 180)
        self.assertIs(
            factory.call_args.kwargs["provider_state"], self.state.return_value
        )

    def test_openai_models_use_the_responses_adapter(self):
        services = self.make_services()
        request = ModelRequest(model="gpt-6-luna", instructions="i", input="hello")
        openai = Mock()
        openai.complete.return_value = ModelTurn(text="OpenAI")
        stream = Mock()
        stream.stream.return_value = {"status": "completed"}
        with (
            patch.object(openai_requests, "OpenAIResponsesClient", return_value=openai),
            patch.object(openai_stream, "OpenAIStreamClient", return_value=stream),
            patch.object(model_wiring, "ClaudeMessagesClient") as claude_factory,
        ):
            self.assertEqual(services.complete(request), ModelTurn(text="OpenAI"))
            turn = services.stream(request, Mock(), cancel_event=None)
        openai.complete.assert_called_once_with(request)
        self.assertEqual(
            stream.stream.call_args.args[0],
            openai_responses_adapter.request_payload(request),
        )
        self.assertEqual(turn, ModelTurn(stop_reason="completed"))
        claude_factory.assert_not_called()

    def test_claude_families_resolve_their_model_without_an_openai_fallback(self):
        services = self.make_services()
        self.values[CLAUDE_MODELS_KEY] = json.dumps(
            {
                "newest": {"opus": "claude-opus-5-6"},
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        )
        claude = Mock()
        claude.complete.return_value = ModelTurn(text="Claude")
        claude.stream.side_effect = AppError(
            503, "x", reason="provider_unavailable", upstream_status=529
        )
        openai = Mock()
        on_delta = Mock()
        with (
            patch.object(model_wiring, "ClaudeMessagesClient", return_value=claude),
            patch.object(openai_requests, "OpenAIResponsesClient", openai),
            patch.object(openai_stream, "OpenAIStreamClient", openai),
        ):
            turn = services.complete(ModelRequest(model="claude-opus", input="x"))
            with self.assertRaises(AppError):
                services.stream(ModelRequest(model="claude-opus"), on_delta)
        self.assertEqual(turn, ModelTurn(text="Claude"))
        self.assertEqual(claude.complete.call_args.args[0].model, "claude-opus-5-6")
        self.assertEqual(claude.stream.call_args.args[0].model, "claude-opus-5-6")
        self.assertIs(claude.stream.call_args.args[1], on_delta)
        # A failing Claude request never reaches OpenAI.
        self.assertEqual(openai.mock_calls, [])
        self.assertEqual(
            json.loads(self.values[CLAUDE_MODELS_KEY])["working"],
            {"opus": "claude-opus-5-6"},
        )

    def test_claude_client_uses_the_anthropic_configuration(self):
        services = self.make_services()
        with patch.object(provider_http, "MAX_EXTERNAL_RESPONSE_BYTES", 4096):
            client = services.claude_client()
        self.assertEqual(client.config.api_key, "anthropic-test-key")
        self.assertEqual(client.config.base_url, "https://claude.example.invalid")
        self.assertEqual(client.config.default_base_url, "https://api.anthropic.com")
        self.assertEqual(client.config.timeout_seconds, 600)
        self.assertEqual(client.config.max_response_bytes, 4096)

    def test_claude_models_are_one_resolver_over_the_stored_state(self):
        services = self.make_services()
        self.assertIs(services.claude_models(), services.claude_models())
        # An unreadable stored state reads as empty, not as an error.
        self.values[CLAUDE_MODELS_KEY] = "not json"
        self.assertIsNone(services.claude_models().status()["opus"]["rejected"])
        self.values[CLAUDE_MODELS_KEY] = json.dumps(
            {"newest": {"opus": "claude-opus-5-6"}}
        )
        self.assertEqual(
            services.claude_models().status()["opus"]["model"], "claude-opus-5-6"
        )

    def test_audio_client_transcribes_through_openai_with_its_own_limits(self):
        services = self.make_services()
        with patch.object(
            audio_provider, "AudioTranscriptionClient", return_value="audio"
        ) as factory:
            self.assertEqual(services.audio_transcription_client(), "audio")
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["max_audio_bytes"], 2048)
        self.assertEqual(kwargs["openai_api_key"], "openai-test-key")
        self.assertEqual(kwargs["openai_transcription_model"], "gpt-transcribe")
        self.assertEqual(kwargs["response_timeout_seconds"], 90)
        self.assertIs(kwargs["http_client"], self.http.return_value)
        self.assertIs(kwargs["provider_state"], self.state.return_value)

    def test_stream_opener_patch_targets_remain_at_provider_owners(self):
        services = self.make_services()
        opener = Mock(name="opener")
        with (
            patch.object(provider_http, "urlopen", opener),
            patch.object(
                openai_stream, "OpenAIStreamClient", return_value="openai-stream"
            ) as openai_factory,
        ):
            self.assertEqual(services.openai_stream_client(), "openai-stream")

        self.assertIs(openai_factory.call_args.kwargs["opener"], opener)
        self.assertEqual(openai_factory.call_args.args[0].timeout, 600)
        self.assertIs(openai_factory.call_args.args[2], self.thinking)


if __name__ == "__main__":
    unittest.main()
