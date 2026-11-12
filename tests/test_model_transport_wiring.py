from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.providers import http as provider_http
from backend.providers import openai_requests, openai_responses_adapter, openai_stream
from backend.providers.model_assembly import (
    CLAUDE_MODELS_KEY,
    AudioTranscriptionSettings,
    ModelEndpointSettings,
    ModelProviderDiagnostics,
    ModelProviderOwners,
    ModelResponseLimits,
    ModelTransportAssembly,
    ModelTransportClock,
)
from backend.providers.model_seam import ModelRequest, ModelTurn


class ModelTransportAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        config = SimpleNamespace(
            openai_api_key="openai-test-key",
            openai_base_url="https://openai.example.invalid/v1",
            anthropic_api_key="anthropic-test-key",
            anthropic_base_url="https://claude.example.invalid",
        )
        self.values = {}
        settings = Mock(return_value="high")
        http_client = Mock(name="provider_http_client")
        provider_state = Mock(name="provider_state")
        config_provider = Mock(return_value=config)
        state_provider = Mock(return_value=provider_state)
        http_provider = Mock(return_value=http_client)
        assembly = ModelTransportAssembly(
            dependencies=ModelTransportAssembly.Inputs(
                providers=ModelProviderOwners(
                    config=config_provider,
                    selected_thinking_level=settings,
                    http_client=http_provider,
                    state_service=state_provider,
                    read_value=self.values.get,
                    write_value=self.values.__setitem__,
                ),
                endpoints=ModelEndpointSettings(
                    default_openai_base_url="https://api.openai.com/v1",
                    openai_responses_path="/responses",
                    json_media_type="application/json",
                    response_timeout_seconds=600,
                    request_timeout_seconds=180,
                ),
                audio=AudioTranscriptionSettings(max_audio_bytes=2048),
                diagnostics=ModelProviderDiagnostics(
                    diagnostic_capture=Mock(name="diagnostics"),
                    logger=Mock(name="logger"),
                    app_version="test-version",
                ),
                limits=ModelResponseLimits(
                    max_response_bytes=lambda: 4096,
                ),
                clock=ModelTransportClock(
                    utc_now=Mock(return_value="2026-09-26T00:00:00Z"),
                    monotonic=Mock(return_value=10.0),
                    wait=Mock(),
                ),
            )
        )
        return assembly, config_provider, settings, http_provider, state_provider

    def test_openai_adapter_resolves_active_config_and_shared_owners_per_call(self):
        assembly, config, settings, http, state = self.make_assembly()
        config.assert_not_called()
        with patch.object(
            openai_requests, "OpenAIResponsesClient", return_value="client"
        ) as factory:
            self.assertEqual(assembly.openai_responses_client(), "client")

        config.assert_called_once()
        settings.assert_not_called()
        http.assert_called_once()
        state.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["api_key"], "openai-test-key")
        self.assertIs(factory.call_args.kwargs["thinking_level"], settings)
        self.assertIs(factory.call_args.kwargs["http_client"], http.return_value)
        # A plain request keeps its own limit, apart from the streamed one.
        self.assertEqual(factory.call_args.kwargs["response_timeout_seconds"], 180)
        self.assertIs(factory.call_args.kwargs["provider_state"], state.return_value)

    def test_openai_models_use_the_responses_adapter(self):
        assembly, *_ = self.make_assembly()
        request = ModelRequest(model="gpt-6-luna", instructions="i", input="hello")
        openai = Mock()
        openai.complete.return_value = ModelTurn(text="OpenAI")
        stream = Mock()
        stream.stream.return_value = {"status": "completed"}
        claude = Mock()
        with (
            patch.object(assembly, "openai_responses_client", return_value=openai),
            patch.object(assembly, "openai_stream_client", return_value=stream),
            patch.object(assembly, "claude_client", return_value=claude),
        ):
            self.assertEqual(assembly.complete(request), ModelTurn(text="OpenAI"))
            turn = assembly.stream(request, Mock(), cancel_event=None)
        openai.complete.assert_called_once_with(request)
        self.assertEqual(
            stream.stream.call_args.args[0],
            openai_responses_adapter.request_payload(request),
        )
        self.assertEqual(turn, ModelTurn(stop_reason="completed"))
        claude.complete.assert_not_called()
        claude.stream.assert_not_called()

    def test_claude_families_resolve_their_model_without_an_openai_fallback(self):
        assembly, *_ = self.make_assembly()
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
            patch.object(assembly, "claude_client", return_value=claude),
            patch.object(assembly, "openai_responses_client", return_value=openai),
            patch.object(assembly, "openai_stream_client", return_value=openai),
        ):
            turn = assembly.complete(ModelRequest(model="claude-opus", input="x"))
            with self.assertRaises(AppError):
                assembly.stream(ModelRequest(model="claude-opus"), on_delta)
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
        assembly, *_ = self.make_assembly()
        client = assembly.claude_client()
        self.assertEqual(client.config.api_key, "anthropic-test-key")
        self.assertEqual(client.config.base_url, "https://claude.example.invalid")
        self.assertEqual(client.config.default_base_url, "https://api.anthropic.com")
        self.assertEqual(client.config.timeout_seconds, 600)
        self.assertEqual(client.config.max_response_bytes, 4096)

    def test_stream_opener_patch_targets_remain_at_provider_owners(self):
        assembly, _config, _settings, _http, _state = self.make_assembly()
        opener = Mock(name="opener")
        with (
            patch.object(provider_http, "urlopen", opener),
            patch.object(
                openai_stream, "OpenAIStreamClient", return_value="openai-stream"
            ) as openai_factory,
        ):
            self.assertEqual(assembly.openai_stream_client(), "openai-stream")

        self.assertIs(openai_factory.call_args.kwargs["opener"], opener)
        self.assertEqual(openai_factory.call_args.args[0].timeout, 600)
        self.assertIs(
            openai_factory.call_args.args[2], assembly._selected_thinking_level
        )


if __name__ == "__main__":
    unittest.main()
