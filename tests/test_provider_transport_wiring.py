from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.providers import http as provider_http
from backend.providers import intervals_client as intervals_client_module
from backend.providers.openai_error_classifier import OpenAIErrorClassifier
from backend.providers.transport_wiring import build_provider_transport


class ProviderTransportWiringTests(unittest.TestCase):
    def make_services(self):
        self.late = {
            name: Mock(name=name)
            for name in ("provider_state", "current_config", "athlete_now")
        }
        self.operation = Mock(name="intervals_operation")
        self.operation_context = Mock(name="operation_context")
        self.logger = Mock(name="logger")
        self.capture = Mock(name="diagnostic_capture")
        return build_provider_transport(
            app_version="test",
            logger=self.logger,
            diagnostic_capture=self.capture,
            redact_text=str,
            provider_state=self.late["provider_state"],
            operation_context=self.operation_context,
            current_config=self.late["current_config"],
            athlete_now=self.late["athlete_now"],
            intervals_operation=self.operation,
        )

    def test_building_calls_no_late_dependency(self):
        self.make_services()
        for dependency in (*self.late.values(), self.operation_context):
            dependency.assert_not_called()

    def test_json_client_comes_from_the_shared_cache_with_the_live_opener(self):
        services = self.make_services()
        opener = Mock(name="opener")
        with (
            patch.object(provider_http, "urlopen", opener),
            patch.object(provider_http, "JSON_HTTP_CLIENT_CACHE") as cache,
        ):
            self.assertIs(services.json_http_client(), cache.get.return_value)
        args = cache.get.call_args
        self.assertEqual(
            args.args[:3],
            ("test", provider_http.MAX_EXTERNAL_RESPONSE_BYTES, self.logger),
        )
        self.assertIs(args.args[3], self.capture)
        self.assertIs(args.args[6], self.operation_context)
        details = args.kwargs["provider_error_details"]
        self.assertIsInstance(details, OpenAIErrorClassifier)
        # The cache rebinds the transport when the provider state changes.
        self.assertIs(details.cache_key(), self.late["provider_state"].return_value)
        self.assertIs(args.kwargs["opener"], opener)

    def test_intervals_client_uses_the_shared_transport_and_active_config(self):
        services = self.make_services()
        request = Mock(name="request")
        with (
            patch.object(
                provider_http,
                "JSON_HTTP_CLIENT_CACHE",
                Mock(get=Mock(return_value=Mock(request=request))),
            ),
            patch.object(
                intervals_client_module, "IntervalsClient", return_value="client"
            ) as factory,
        ):
            explicit = Mock(name="explicit")
            self.assertEqual(services.intervals_client(explicit), "client")
            self.late["current_config"].assert_not_called()
            self.assertIs(factory.call_args.args[0], explicit)
            self.assertEqual(services.intervals_client(), "client")
        self.late["current_config"].assert_called_once_with()
        self.assertIs(
            factory.call_args.args[0], self.late["current_config"].return_value
        )
        self.assertIs(factory.call_args.kwargs["request"], request)
        self.assertIs(factory.call_args.kwargs["now"], self.late["athlete_now"])
        self.assertIs(factory.call_args.kwargs["operation"], self.operation)


if __name__ == "__main__":
    unittest.main()
