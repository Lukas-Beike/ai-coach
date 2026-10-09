from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.providers import openai
from backend.providers.model_assembly import (
    AudioTranscriptionSettings,
    ModelBackgroundPolicy,
    ModelEndpointSettings,
    ModelProviderDiagnostics,
    ModelProviderOwners,
    ModelTransportAssembly,
    ModelTransportClock,
)


class ModelTransportAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        config = SimpleNamespace(
            openai_api_key="openai-test-key",
            openai_base_url="https://openai.example.invalid/v1",
        )
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
                ),
                endpoints=ModelEndpointSettings(
                    default_openai_base_url="https://api.openai.com/v1",
                    openai_responses_path="/responses",
                    json_media_type="application/json",
                    response_timeout_seconds=180,
                ),
                audio=AudioTranscriptionSettings(max_audio_bytes=2048),
                diagnostics=ModelProviderDiagnostics(
                    diagnostic_capture=Mock(name="diagnostics"),
                    logger=Mock(name="logger"),
                    app_version="test-version",
                ),
                background=ModelBackgroundPolicy(
                    background_poll_seconds=2,
                    background_max_seconds=60,
                    max_response_bytes=lambda: 4096,
                ),
                clock=ModelTransportClock(
                    utc_now=Mock(return_value="2026-09-26T00:00:00Z"),
                    monotonic=Mock(return_value=10.0),
                    wall_time=Mock(return_value=20.0),
                    wait=Mock(),
                ),
            )
        )
        return assembly, config_provider, settings, http_provider, state_provider

    def test_openai_adapter_resolves_active_config_and_shared_owners_per_call(self):
        assembly, config, settings, http, state = self.make_assembly()
        config.assert_not_called()
        with patch.object(
            openai, "OpenAIResponsesClient", return_value="client"
        ) as factory:
            self.assertEqual(assembly.openai_responses_client(), "client")

        config.assert_called_once()
        settings.assert_not_called()
        http.assert_called_once()
        state.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["api_key"], "openai-test-key")
        self.assertIs(factory.call_args.kwargs["thinking_level"], settings)
        self.assertIs(factory.call_args.kwargs["http_client"], http.return_value)
        self.assertIs(factory.call_args.kwargs["provider_state"], state.return_value)

    def test_stream_opener_patch_targets_remain_at_provider_owners(self):
        assembly, _config, _settings, _http, _state = self.make_assembly()
        opener = Mock(name="opener")
        with (
            patch.object(openai, "urlopen", opener),
            patch.object(
                openai, "OpenAIStreamClient", return_value="openai-stream"
            ) as openai_factory,
        ):
            self.assertEqual(assembly.openai_stream_client(), "openai-stream")

        self.assertIs(openai_factory.call_args.kwargs["opener"], opener)
        self.assertEqual(openai_factory.call_args.args[0].timeout, 180)
        self.assertIs(
            openai_factory.call_args.args[2], assembly._selected_thinking_level
        )


if __name__ == "__main__":
    unittest.main()
