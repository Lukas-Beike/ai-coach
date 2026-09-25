"""Server integration tests for providers."""

import json
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import call, Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from backend.coach import streams as coach_streams
from backend.errors import ClientDisconnected
from backend.http_api import responses
from backend.providers import calendar as calendar_provider, gemini as gemini_provider, http as provider_http, openai as openai_provider
from backend.sync import garmin as garmin_sync, observation as sync_observation
from server_test_support import _transcribe_via_http_route, server, ServerTestCase
from support import build_gemini_request_payload


class ServerProvidersTests(ServerTestCase):

    def test_morning_recovery_service_is_shared_and_recomposed_for_config(self):
        original = server.morning_body_battery_service()
        self.assertIs(original, server.morning_body_battery_service())

        updated_config = replace(
            server.CONFIG, garmin_email="updated-test@example.invalid"
        )
        with patch.object(server, "CONFIG", updated_config):
            updated = server.morning_body_battery_service()
            self.assertIsNot(updated, original)
            self.assertIs(updated, server.morning_body_battery_service())

        self.assertIsNot(server.morning_body_battery_service(), updated)

    def test_persisted_job_is_revalidated_before_provider_dispatch(self):
        with patch.object(server.GarminSyncService, "sync") as sync:
            with self.assertRaises(server.AppError) as raised:
                server.sync_job_executor().execute({
                    "id": "unsupported-job",
                    "provider": "garmin",
                    "type": "removed_job_type",
                    "payload": "{}",
                })
        self.assertEqual(raised.exception.reason, "invalid_job_request")
        sync.assert_not_called()

    def test_finite_retention_clears_unstamped_gemini_history(self):
        server.key_value_service().set("gemini_conversation_history", json.dumps([{"role": "user", "parts": [{"text": "old coach context"}]}]))
        server.key_value_service().set("gemini_call_names", json.dumps({"gemini_old": "save_checkin"}))
        with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):
            server.initialise_database()
        self.assertEqual(server.key_value_service().get("gemini_conversation_history"), "[]")
        self.assertEqual(server.key_value_service().get("gemini_call_names"), "{}")

    def test_garmin_capability_breaker_pauses_repeated_same_error(self):
        error = server.AppError(503, "provider unavailable", reason="network_error")
        service = server.garmin_sync_state_service()
        for _ in range(garmin_sync.GARMIN_CAPABILITY_FAILURE_LIMIT):
            service.record_capability_failure("body_battery", error)
        self.assertFalse(service.capability_allowed("body_battery"))
        state = service.capability_state("body_battery")
        self.assertEqual(
            state["count"], garmin_sync.GARMIN_CAPABILITY_FAILURE_LIMIT
        )
        self.assertEqual(state["error_class"], "network_error")
        service.record_capability_success("body_battery")
        self.assertTrue(service.capability_allowed("body_battery"))

    def test_output_text_falls_back_to_nested_content(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}]}
        self.assertEqual(openai_provider.response_text(response), "Hello")

    def test_gemini_normalizes_tool_calls_and_preserves_function_history(self):
        captured = []
        responses = [
            {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": "save_checkin", "args": {"payload": {"energy": 7}}}}]}}], "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 3, "totalTokenCount": 14}},
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "Check-in gespeichert."}]}}], "usageMetadata": {"promptTokenCount": 14, "candidatesTokenCount": 4, "totalTokenCount": 18}},
        ]

        def fake_http_json(method, url, payload=None, headers=None, **kwargs):
            captured.append({"method": method, "url": url, "payload": payload, "headers": headers})
            return responses.pop(0)

        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        tool = {"type": "function", "name": "save_checkin", "description": "Save check-in", "parameters": {"type": "object", "properties": {"payload": {"type": "object"}}}}
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", side_effect=fake_http_json):
            initial = server.gemini_conversation_response_service().request({"model": "gemini-3.8-flash", "conversation": "gemini_test", "instructions": "Coach rules", "input": "Speichere meine Tagesform.", "tools": [tool], "tool_choice": "auto", "max_output_tokens": 321})
            call = next(item for item in initial["output"] if item["type"] == "function_call")
            followup = server.gemini_conversation_response_service().request({"conversation": "gemini_test", "instructions": "Coach rules", "input": [{"type": "function_call_output", "call_id": call["call_id"], "output": '{"ok":true}'}], "tools": [tool], "tool_choice": "auto"})

        self.assertEqual(captured[0]["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
        self.assertEqual(captured[0]["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertEqual(captured[0]["payload"]["systemInstruction"]["parts"][0]["text"], "Coach rules")
        self.assertEqual(captured[0]["payload"]["tools"][0]["functionDeclarations"][0]["name"], "save_checkin")
        self.assertEqual(captured[0]["payload"]["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"], tool["parameters"])
        function_response = next(
            part["functionResponse"]
            for content in captured[1]["payload"]["contents"]
            for part in content.get("parts", [])
            if "functionResponse" in part
        )
        self.assertEqual(function_response["name"], "save_checkin")
        self.assertEqual(openai_provider.response_text(followup), "Check-in gespeichert.")

    def test_gemini_stream_forwards_chunks_and_aggregates_the_final_response(self):
        captured = {}

        class StreamResponse:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                yield b'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"Hallo "}]}}]}\n'
                yield b'\n'
                yield b'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"Welt"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2,"totalTokenCount":7}}\n'
                yield b'\n'

        def fake_urlopen(request, **_kwargs):
            captured["request"] = request
            return StreamResponse()

        deltas = []
        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        with patch.object(server, "CONFIG", config), patch.object(gemini_provider, "urlopen", side_effect=fake_urlopen):
            result = server.coach_response_transport().stream_request(
                {"_ai_provider": "gemini", "model": "gemini-3.8-flash", "input": "BegrÃ¼ÃŸe mich."},
                deltas.append,
            )

        self.assertEqual(deltas, ["Hallo ", "Welt"])
        self.assertEqual(openai_provider.response_text(result), "Hallo Welt")
        self.assertEqual(result["usage"]["total_tokens"], 7)
        self.assertEqual(captured["request"].full_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse")
        self.assertEqual(captured["request"].headers["X-goog-api-key"], "test-gemini-key")

    def test_gemini_stream_preserves_response_too_large_contract(self):
        class StreamResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                yield b"data: {}\n"

        config = replace(server.CONFIG, gemini_api_key="test-gemini-key")
        with (
            patch.object(server, "CONFIG", config),
            patch.object(provider_http, "MAX_EXTERNAL_RESPONSE_BYTES", 1),
            patch.object(gemini_provider, "urlopen", return_value=StreamResponse()),
            self.assertRaises(server.AppError) as raised,
        ):
            server.gemini_conversation_response_service().stream({"model": "gemini-3.8-flash", "input": "test"}, lambda _: None)

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.reason, "response_too_large")

    def test_gemini_persists_tool_response_before_a_failed_followup(self):
        responses = [
            {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": "save_checkin", "args": {}}}]}}]},
            server.AppError(429, "Gemini ist ausgelastet.", reason="rate_limit_exceeded"),
        ]

        def fake_http_json(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", side_effect=fake_http_json):
            initial = server.gemini_conversation_response_service().request({"conversation": "gemini-persist-response", "input": "Speichere meine Tagesform.", "parallel_tool_calls": False})
            call = next(item for item in initial["output"] if item["type"] == "function_call")
            with self.assertRaises(server.AppError):
                server.gemini_conversation_response_service().request({"conversation": "gemini-persist-response", "input": [{"type": "function_call_output", "call_id": call["call_id"], "output": '{"ok":true}'}], "parallel_tool_calls": False})

        history = json.loads(server.key_value_service().get("gemini_conversation_history") or "[]")
        self.assertEqual(history[-2]["parts"][0]["functionCall"]["name"], "save_checkin")
        self.assertEqual(history[-1]["parts"][0]["functionResponse"]["name"], "save_checkin")

    def test_gemini_rejects_parallel_tool_calls_when_coach_disables_them(self):
        response = {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "save_checkin", "args": {}}},
            {"functionCall": {"name": "save_profile", "args": {}}},
        ]}}]}
        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", return_value=response):
            with self.assertRaises(server.AppError) as raised:
                server.gemini_conversation_response_service().request({"conversation": "gemini-single-tool", "input": "Aktualisiere meine Daten.", "parallel_tool_calls": False})

        self.assertEqual(raised.exception.reason, "parallel_tool_calls_unsupported")
        self.assertEqual(json.loads(server.key_value_service().get("gemini_conversation_history") or "[]"), [])

    def test_gemini_transcription_keeps_audio_server_side_and_returns_text(self):
        captured = {}

        def fake_http_json(method, url, payload=None, headers=None, **kwargs):
            captured.update({"method": method, "url": url, "payload": payload, "headers": headers})
            return {"candidates": [{"content": {"role": "model", "parts": [{"text": "Wie soll ich morgen trainieren?"}]}}]}

        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", side_effect=fake_http_json):
            result = _transcribe_via_http_route(b"fake-webm-audio", "audio/webm;codecs=opus")

        self.assertEqual(result, {"transcript": "Wie soll ich morgen trainieren?"})
        self.assertEqual(captured["headers"]["x-goog-api-key"], "test-gemini-key")
        audio_part = captured["payload"]["contents"][0]["parts"][0]["inlineData"]
        self.assertEqual(audio_part["mimeType"], "audio/webm")
        self.assertNotIn("fake-webm-audio", str(captured["payload"]))

    def test_ai_provider_selection_keeps_models_separate(self):
        config = replace(server.CONFIG, openai_api_key="test-openai-key", gemini_api_key="test-gemini-key", ai_provider="openai")
        with patch.object(server, "CONFIG", config):
            self.assertEqual(server.SETTINGS.selected_ai_provider(), "openai")
            server.SETTINGS.save_model("gpt-6-luna")
            provider_state = server.SETTINGS.save_ai_provider("gemini")
            self.assertEqual(provider_state["provider"], "gemini")
            self.assertEqual(provider_state["model"], "gemini-3.8-flash")
            self.assertEqual([option["id"] for option in provider_state["model_options"]], ["gemini-3.8-flash", "gemini-2.5-pro"])
            self.assertEqual(server.SETTINGS.selected_model(), "gemini-3.8-flash")
            server.SETTINGS.save_model("gemini-2.5-pro")
            server.SETTINGS.save_ai_provider("openai")
            self.assertEqual(server.SETTINGS.selected_model(), "gpt-6-luna")

    def test_gemini_key_is_redacted_from_diagnostics_text(self):
        key = "AIza" + "a" * 35
        with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):
            self.assertNotIn(key, server.REDACTOR.redact_text(f"Gemini request failed: {key}"))

    def test_gemini_turn_uses_its_captured_provider_and_reasoning_level(self):
        config = replace(server.CONFIG, openai_api_key="test-openai-key", gemini_api_key="test-gemini-key", ai_provider="openai")
        payload = {"_ai_provider": "gemini", "model": "gemini-3.8-flash", "input": "Prüfe die Form.", "reasoning": {"effort": "low"}}
        with patch.object(server, "CONFIG", config), patch.object(server, "gemini_conversation_response_service") as service_factory, patch.object(server.openai_provider.OpenAIResponsesClient, "responses") as openai:
            service_factory.return_value.request.return_value = {"output_text": "ok"}
            self.assertEqual(server.coach_response_transport().request(payload)["output_text"], "ok")
        service_factory.return_value.request.assert_called_once_with(payload)
        openai.assert_not_called()
        request, _, _ = build_gemini_request_payload(server, payload, "gemini-3.8-flash")
        self.assertEqual(request["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})

    def test_gemini_background_job_is_not_replayed_after_restart(self):
        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="test-gemini-key", ai_provider="gemini")
        server.key_value_service().set("gemini_conversation_history", json.dumps([
            {"role": "user", "parts": [{"text": "Erstelle einen Plan."}]},
            {"role": "model", "parts": [{"functionCall": {"name": "stage_training_plan", "args": {}}}]},
        ]))
        with patch.object(server, "CONFIG", config):
            server.coach_job_submission_service().enqueue(
                "Erstelle einen Trainingsplan für die nächsten 2 Wochen.",
                "turn-gemini-background-restart",
                "csrf-gemini-background-restart",
            )
            self.assertIsNotNone(server.coach_job_store().claim())
            self.assertEqual(server.coach_job_store().resume_interrupted(server.coach_turn_failure_service()), 0)
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            command = db.execute("SELECT status, receipt FROM coach_commands WHERE client_turn_id=?", ("turn-gemini-background-restart",)).fetchone()
        self.assertEqual(command["status"], "completed")
        self.assertEqual(json.loads(command["receipt"])["status"], "failed")
        self.assertEqual(server.gemini_conversation_history_service().load(), [
            {"role": "user", "parts": [{"text": "Erstelle einen Plan."}]},
            {"role": "model", "parts": [{"functionCall": {"name": "stage_training_plan", "args": {}}}]},
        ])

    def test_gemini_reset_deletes_an_existing_openai_conversation(self):
        server.key_value_service().set("openai_conversation_id", "conv-test")
        config = replace(server.CONFIG, openai_api_key="test-openai-key", gemini_api_key="test-gemini-key", ai_provider="gemini")
        with patch.object(server, "CONFIG", config), patch.object(server.openai_provider.OpenAIResponsesClient, "delete_conversation", return_value=True) as delete:
            result = server.coach_conversation_reset_service().reset()
        delete.assert_called_once_with("conv-test")
        self.assertTrue(result["remote_conversation_deleted"])

    def test_gemini_http_errors_keep_the_provider_status(self):
        upstream_error = HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"error":{"status":"UNAUTHENTICATED"}}'),
        )
        with patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent", {}, service="gemini")
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.reason, "authentication_or_permission")

    def test_openai_request_uses_configured_compatible_provider_endpoint(self):
        captured = {}

        def fake_http_json(method, url, payload=None, headers=None, **kwargs):
            captured.update({"method": method, "url": url, "payload": payload, "headers": headers, "kwargs": kwargs})
            return {"id": "resp-test", "status": "completed", "usage": {}}

        config = replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1")
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", side_effect=fake_http_json):
            result = server.openai_responses_client().request(
                "/responses", {"model": "foundry-deployment", "input": "Hi"}
            )

        self.assertEqual(result["id"], "resp-test")
        self.assertEqual(captured["url"], "https://foundry.example.invalid/openai/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")

    def test_responses_stream_request_uses_configured_compatible_provider_endpoint(self):
        class FakeResponse:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                response = {"id": "resp-test", "status": "completed", "output": [], "usage": {}}
                stream = "event: response.completed\ndata: " + json.dumps({"type": "response.completed", "response": response}) + "\n\n"
                yield from (line.encode() for line in stream.splitlines(keepends=True))

        config = replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")
        with patch.object(server, "CONFIG", config), patch.object(openai_provider, "urlopen", return_value=FakeResponse()) as urlopen:
            server.coach_response_transport().stream_request({"model": "foundry-deployment"}, lambda _: None)

        self.assertEqual(urlopen.call_args.args[0].full_url, "https://foundry.example.invalid/openai/v1/responses")

    def test_responses_request_uses_selected_thinking_level(self):
        server.SETTINGS.save_thinking_level("low")
        captured = {}

        def fake_openai(_method, _url, payload=None, **_kwargs):
            captured.update(payload)
            return {"output_text": "ok", "output": []}

        config = replace(server.CONFIG, openai_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            server.provider_http_client(), "request", side_effect=fake_openai
        ):
            server.coach_response_transport().request({"model": "gpt-6-luna", "input": "test"})
        self.assertEqual(captured["reasoning"], {"effort": "low"})

    def test_openai_background_creation_defers_usage_recording(self):
        response = {"id": "resp_background_usage", "status": "queued", "usage": {}}
        with patch.object(server.provider_http_client(), "request", return_value=response), patch.object(
            server.provider_state_service(), "record_usage"
        ) as record_usage:
            server.openai_responses_client().request(
                "/responses",
                {"model": "gpt-6-luna", "background": True, "store": True, "input": "test"},
            )
        record_usage.assert_not_called()

    def test_openai_client_composition_keeps_background_limits_and_runtime_hooks(self):
        client = server.openai_responses_client()

        self.assertEqual(client.background_poll_seconds, server.OPENAI_BACKGROUND_POLL_SECONDS)
        self.assertEqual(client.background_max_seconds, server.OPENAI_BACKGROUND_MAX_SECONDS)
        self.assertIs(client.monotonic, server.time.monotonic)
        self.assertIs(client.wait, server.time.sleep)

    def test_attached_durable_job_uses_provider_stream_instead_of_background_polling(self):
        csrf_hash = "csrf-attached-provider-stream"
        server.key_value_service().set("openai_conversation_id", "conv-attached-provider-stream")
        server.coach_job_submission_service().enqueue(
            "Wie soll ich heute trainieren?", "turn-attached-provider-stream", csrf_hash,
            operation_id="operation-attached-provider-stream",
        )
        self.assertIsNotNone(server.coach_job_store().claim())
        deltas = []

        def streamed_response(_payload, on_delta, _cancel_event, **kwargs):
            if kwargs.get("on_response_id"):
                kwargs["on_response_id"]("resp_attached_stream")
            on_delta("Heute locker.")
            return {"id": "resp_attached_stream", "status": "completed", "output_text": "Heute locker."}

        with patch.object(server, "coach_response_transport") as transport_factory:
            transport_factory.return_value.stream_request.side_effect = streamed_response
            result = server.coach_chat_turn_service().run(
                "Wie soll ich heute trainieren?", client_turn_id="turn-attached-provider-stream",
                session_csrf_hash=csrf_hash, background_job=True, on_text_delta=deltas.append,
            )

        transport_factory.return_value.stream_request.assert_called_once()
        transport_factory.return_value.background_request.assert_not_called()
        self.assertEqual(deltas, ["Heute locker."])
        self.assertEqual(result["message"]["content"], "Heute locker.")

    def test_diagnostics_redact_credentials_from_logs(self):
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        server.LOGGER.error("failed request with sk-test-secret-value")
        for handler in server.LOGGER.handlers:
            handler.flush()
        report_text = json.dumps(server.diagnostic_report_service().report())
        self.assertNotIn("sk-test-secret-value", report_text)
        self.assertIn("logs", server.diagnostic_report_service().report())
        self.assertIn("openai", server.diagnostic_report_service().report())

    def test_redaction_covers_garmin_email_encoded_url_and_structural_credentials(self):
        email = "Athlete.Redaction@example.invalid"
        calendar_url = "https://calendar.example.invalid/private/FeedSecret-9aB7cD2eF4gH6iJ8kL0mN.ics?accessToken=calendar-query-secret"
        config = replace(server.CONFIG, garmin_email=email, calendar_ical_url=calendar_url)
        userinfo_url = "https://calendar-user:calendar-password@calendar.example.invalid/family.ics"
        token_url = "https://calendar.example.invalid/feed.ics?provider=family&ACCESS-TOKEN=query-secret"
        long_path_url = "https://calendar.example.invalid/public/9aB7cD2eF4gH6iJ8kL0mN2pQ4rS6tU8vW0xY.ics"
        with patch.object(server, "CONFIG", config):
            samples = " | ".join((
                email,
                email.casefold(),
                quote(email, safe=""),
                calendar_url,
                quote(calendar_url, safe=""),
                userinfo_url,
                token_url,
                long_path_url,
            ))
            redacted = server.REDACTOR.redact_text(samples)
        for secret in (email, calendar_url, quote(email, safe=""), quote(calendar_url, safe=""), "calendar-password", "query-secret"):
            self.assertNotIn(secret.casefold(), redacted.casefold())
        self.assertIn("calendar.example.invalid", redacted)
        self.assertIn("[REDACTED_PATH]", redacted)
        self.assertNotIn("calendar-user", redacted)

    def test_provider_errors_are_classified_and_stored_diagnostics_are_redacted(self):
        email = "garmin.fake.person@example.invalid"
        calendar_url = "https://calendar.example.invalid/private/fake-calendar-token-1234567890.ics"
        config = replace(server.CONFIG, garmin_email=email, calendar_ical_url=calendar_url)
        with patch.object(server, "CONFIG", config):
            with self.assertRaises(server.AppError) as sdk_error:
                server.provider_http.external_call(
                    "garmin",
                    "login",
                    lambda: (_ for _ in ()).throw(RuntimeError(f"login {email}")),
                    logger=server.LOGGER,
                    diagnostic_capture=server.DIAGNOSTIC_CAPTURE,
                    operation_context=sync_observation.operation_context(),
                )
            self.assertEqual(sdk_error.exception.reason, "provider_client_error")
            self.assertNotIn(email, str(sdk_error.exception))

            with patch.object(calendar_provider, "external_calendar_url", return_value=calendar_url), patch.object(
                calendar_provider, "fetch_calendar_feed", side_effect=RuntimeError(f"calendar request failed for {email}")
            ):
                with self.assertRaises(server.AppError) as calendar_error:
                    server.external_calendar_sync_service().sync("test")
            self.assertEqual(calendar_error.exception.reason, "provider_client_error")
            self.assertNotIn(email, str(calendar_error.exception))

            server.key_value_service().set("last_garmin_error", json.dumps([{"source": "login", "message": f"{email} {calendar_url}"}]))
            state = server.garmin_projection_service().public_state()
            report = json.dumps(server.diagnostic_report_service().report(), ensure_ascii=False)
        self.assertNotIn(email, json.dumps(state, ensure_ascii=False))
        self.assertNotIn(calendar_url, report)
        self.assertIn("calendar.example.invalid", report)

    def test_http_provider_error_api_text_is_safe_and_bodies_are_not_logged(self):
        email = "fake.garmin@example.invalid"
        calendar_url = "https://calendar.example.invalid/private/fake-calendar-token-1234567890.ics"
        config = replace(server.CONFIG, garmin_email=email, calendar_ical_url=calendar_url)
        error_body = json.dumps({"error": {"message": f"rejected {email} {calendar_url}"}}).encode("utf-8")
        upstream_error = HTTPError("https://intervals.icu/api/v1/athlete/0", 422, "Unprocessable Entity", {}, BytesIO(error_body))
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request("GET", "https://intervals.icu/api/v1/athlete/0", service="intervals")
        self.assertEqual(raised.exception.reason, "provider_http_error")
        self.assertNotIn(email, raised.exception.message)
        self.assertNotIn(calendar_url, raised.exception.message)

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, *args):
                return b'{"body_marker":"do-not-log-response-body"}'

        with patch.object(server.provider_http_client(), "opener", return_value=FakeResponse()):
            server.provider_http_client().request("POST", "https://intervals.icu/api/v1/athlete/0", payload={"body_marker": "do-not-log-request-body"}, service="intervals")
        for handler in server.LOGGER.handlers:
            handler.flush()
        log_text = json.dumps(server.recent_log_entries_service().list(), ensure_ascii=False)
        self.assertNotIn("do-not-log-request-body", log_text)
        self.assertNotIn("do-not-log-response-body", log_text)

    def test_user_enabled_diagnostic_capture_keeps_response_shape_without_content(self):
        self.assertFalse(server.DIAGNOSTIC_CAPTURE.status()["active"])
        enabled = server.DIAGNOSTIC_CAPTURE.set_enabled(True)
        self.assertTrue(enabled["active"])
        response = {
            "bodyBattery": 82,
            "access_token": "must-never-appear",
            "nested": {"sessionId": "must-also-never-appear", "athlete_note": "must-not-appear"},
        }
        server.provider_http.external_call(
            "garmin",
            "body_battery",
            lambda: response,
            logger=server.LOGGER,
            diagnostic_capture=server.DIAGNOSTIC_CAPTURE,
            operation_context=sync_observation.operation_context(),
        )
        report = server.diagnostic_report_service().report()
        report_text = json.dumps(report, ensure_ascii=False)
        self.assertIn("bodyBattery", report_text)
        self.assertNotIn("must-not-appear", report_text)
        self.assertNotIn("must-never-appear", report_text)
        self.assertNotIn("must-also-never-appear", report_text)
        entries = server.DIAGNOSTIC_CAPTURE.entries()
        self.assertTrue(entries)
        response_capture = entries[-1]["details"]["response"]
        self.assertIn("shape", response_capture)
        self.assertNotIn("content", response_capture)

        server.DIAGNOSTIC_CAPTURE.set_enabled(False)
        self.assertFalse(server.DIAGNOSTIC_CAPTURE.status()["active"])
        server.provider_http.external_call(
            "garmin",
            "body_battery",
            lambda: {"new_marker": "not captured"},
            logger=server.LOGGER,
            diagnostic_capture=server.DIAGNOSTIC_CAPTURE,
            operation_context=sync_observation.operation_context(),
        )
        self.assertNotIn("not captured", json.dumps(server.diagnostic_report_service().report(), ensure_ascii=False))

    def test_upstream_network_failures_are_structured_in_diagnostics(self):
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        with patch.object(
            server.provider_http_client(), "opener", side_effect=URLError("offline")
        ):
            with self.assertRaises(server.AppError):
                server.provider_http_client().request("GET", "https://intervals.icu/api/v1/athlete/0")
        for handler in server.LOGGER.handlers:
            handler.flush()
        entries = server.recent_log_entries_service().list()
        self.assertTrue(any(entry.get("event") == "upstream_network_error" for entry in entries))

    def test_external_http_calls_log_start_and_completion_without_payload(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"activities": [1, 2]}'

        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        with patch.object(server.provider_http_client(), "opener", return_value=FakeResponse()):
            result = server.provider_http_client().request(
                "GET",
                "https://intervals.icu/api/v1/athlete/0/activities?oldest=2026-08-01&newest=2026-08-29",
                service="intervals",
            )
        for handler in server.LOGGER.handlers:
            handler.flush()
        entries = server.recent_log_entries_service().list()
        started = [entry for entry in entries if entry.get("event") == "external_request_started"][-1]
        completed = [entry for entry in entries if entry.get("event") == "external_request_completed"][-1]
        self.assertEqual(result["activities"], [1, 2])
        self.assertEqual(started["context"]["service"], "intervals")
        self.assertEqual(started["context"]["path"], "/api/v1/athlete/[REDACTED_PATH]/activities")
        self.assertEqual(started["context"]["query_keys"], ["newest", "oldest"])
        self.assertEqual(completed["context"]["status"], 200)
        self.assertEqual(completed["context"]["result_fields"], 1)

    def test_openai_credit_balance_exhausted_error_is_classified_and_persisted(self):
        error_body = json.dumps({
            "error": {
                "message": "Your credit balance is exhausted.",
                "type": "insufficient_quota",
                "code": "credit_balance_exhausted",
            }
        }).encode("utf-8")
        upstream_error = HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "Too Many Requests",
            {
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-remaining-tokens": "0",
            },
            BytesIO(error_body),
        )
        with patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request("POST", "https://api.openai.com/v1/responses", payload={}, service="openai")
        self.assertEqual(raised.exception.status, 429)
        self.assertIn("Guthaben", raised.exception.message)
        summary = server.provider_state_service().summary("openai")
        self.assertEqual(summary["status"]["reason"], "credit_balance_exhausted")
        self.assertEqual(summary["status"]["http_status"], 429)
        self.assertEqual(summary["rate_limits"]["remaining_requests"], "0")
        self.assertEqual(summary["rate_limits"]["remaining_tokens"], "0")
        self.assertNotIn("current quota", json.dumps(summary))

    def test_openai_retry_after_is_attached_to_transient_http_error(self):
        error_body = json.dumps({"error": {"code": "rate_limit_exceeded"}}).encode("utf-8")
        upstream_error = HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "Too Many Requests",
            {"retry-after": "7"},
            BytesIO(error_body),
        )
        with patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request("POST", "https://api.openai.com/v1/responses", payload={}, service="openai")
        self.assertEqual(raised.exception.reason, "rate_limit_exceeded")
        self.assertEqual(raised.exception.retry_after_seconds, 7)

    def test_openai_stream_retry_after_is_attached_to_transient_http_error(self):
        error_body = json.dumps({"error": {"code": "rate_limit_exceeded"}}).encode("utf-8")
        upstream_error = HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "Too Many Requests",
            {"retry-after": "9"},
            BytesIO(error_body),
        )
        config = replace(server.CONFIG, openai_api_key="openai-test")
        with (
            patch.object(server, "CONFIG", config),
            patch.object(openai_provider, "urlopen", side_effect=upstream_error),
            self.assertRaises(server.AppError) as raised,
        ):
            server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: None)
        self.assertEqual(raised.exception.reason, "rate_limit_exceeded")
        self.assertEqual(raised.exception.retry_after_seconds, 9)

    def test_streaming_openai_400_is_captured_without_error_message_or_payload(self):
        raw_error = json.dumps({
            "error": {
                "code": "invalid_function_call_output",
                "type": "invalid_request_error",
                "message": "athlete-private provider failure",
            },
        }).encode("utf-8")
        upstream_error = HTTPError(
            "https://api.openai.com/v1/responses", 400, "Bad Request", {"x-request-id": "req_test_456"}, BytesIO(raw_error)
        )
        server.DIAGNOSTIC_CAPTURE.set_enabled(True)
        config = replace(server.CONFIG, openai_api_key="openai-test")
        with patch.object(server, "CONFIG", config), patch.object(openai_provider, "urlopen", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: None)
        self.assertEqual(raised.exception.reason, "conversation_state_invalid")
        captured = server.DIAGNOSTIC_CAPTURE.entries()
        failed = next(entry for entry in reversed(captured) if entry["event"] == "openai_stream_failed")
        self.assertEqual(failed["details"]["error_code"], "invalid_function_call_output")
        self.assertEqual(failed["details"]["request_id"], "req_test_456")
        self.assertNotIn("athlete-private", json.dumps(captured))

    def test_responses_stream_request_emits_deltas_and_validates_only_final_response(self):
        response_payload = {
            "id": "resp-test",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hallo"}]}],
            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
        }

        class FakeResponse:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                stream = (
                    'event: response.output_text.delta\n'
                    'data: {"type":"response.output_text.delta","delta":"Hal"}\n\n'
                    'event: response.output_text.delta\n'
                    'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
                    + "event: response.completed\ndata: "
                    + json.dumps({"type": "response.completed", "response": response_payload})
                    + "\n\n"
                    + "data: [DONE]\n\n"
                )
                yield from (line.encode() for line in stream.splitlines(keepends=True))

        deltas = []
        with patch.object(openai_provider, "urlopen", return_value=FakeResponse()) as urlopen:
            result = server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, deltas.append)
        self.assertEqual("".join(deltas), "Hallo")
        self.assertEqual(result["id"], "resp-test")
        request = urlopen.call_args.args[0]
        self.assertTrue(json.loads(request.data)["stream"])
        self.assertEqual(request.get_header("Accept"), "text/event-stream")
        self.assertNotIn("Hallo", json.dumps(server.recent_log_entries_service().list(), ensure_ascii=False))
        self.assertEqual(server.provider_state_service().summary("openai")["total_tokens"], 6)

    def test_responses_stream_request_preserves_response_too_large_contract_and_byte_count(self):
        class OversizedResponse:
            status = 200
            headers = {
                "x-ratelimit-remaining-requests": "7",
                "x-ratelimit-remaining-tokens": "9000",
            }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                yield b"data: {}\n"

        server.DIAGNOSTIC_CAPTURE.set_enabled(True)
        with (
            patch.object(provider_http, "MAX_EXTERNAL_RESPONSE_BYTES", 1),
            patch.object(openai_provider, "urlopen", return_value=OversizedResponse()),
            self.assertRaises(server.AppError) as raised,
        ):
            server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: None)

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.reason, "response_too_large")
        summary = server.provider_state_service().summary("openai")
        self.assertEqual(summary["rate_limits"]["remaining_requests"], "7")
        self.assertEqual(summary["rate_limits"]["remaining_tokens"], "9000")
        captured = server.DIAGNOSTIC_CAPTURE.entries()
        failed = next(entry for entry in reversed(captured) if entry["event"] == "openai_stream_failed")
        self.assertEqual(failed["details"]["response_bytes"], len(b"data: {}\n"))

    def test_responses_stream_request_cancel_before_provider_call_records_cancelled_usage(self):
        cancel_event = threading.Event()
        cancel_event.set()
        with patch.object(openai_provider, "urlopen") as urlopen:
            with self.assertRaises(server.AppError) as raised:
                server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: None, cancel_event)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        urlopen.assert_not_called()
        self.assertEqual(
            server.provider_state_service().summary("openai")["last_operation"],
            "responses_stream_cancelled",
        )

    def test_responses_stream_request_timeout_is_safe_and_records_provider_failure(self):
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)

        class TimeoutResponse:
            headers = {}
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                raise TimeoutError("test timeout")
                yield b""

        with patch.object(openai_provider, "urlopen", return_value=TimeoutResponse()):
            with self.assertRaises(server.AppError) as raised:
                server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: None)
        self.assertEqual(raised.exception.reason, "provider_timeout")
        self.assertEqual(raised.exception.status, 504)
        self.assertEqual(
            server.provider_state_service().summary("openai")["status"]["reason"],
            "provider_timeout",
        )
        failures = [entry for entry in server.recent_log_entries_service().list() if entry.get("event") == "external_request_failed"]
        self.assertEqual(failures[-1]["context"]["reason"], "provider_timeout")

    def test_openai_stream_client_uses_runtime_state_and_diagnostics(self):
        client = server.openai_stream_client()

        self.assertIs(client.telemetry.provider_state, server.provider_state_service())
        self.assertIs(client.telemetry.diagnostic_capture, server.DIAGNOSTIC_CAPTURE)
        self.assertIs(client.telemetry.logger, server.LOGGER)
        self.assertEqual(client.config.max_bytes, provider_http.MAX_EXTERNAL_RESPONSE_BYTES)
        self.assertIs(client.opener, openai_provider.urlopen)

    def test_responses_stream_request_client_disconnect_records_cancelled_usage(self):
        class DisconnectResponse:
            headers = {}
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                yield b'event: response.output_text.delta\n'
                yield b'data: {"delta":"partial"}\n'
                yield b'\n'

        with patch.object(openai_provider, "urlopen", return_value=DisconnectResponse()):
            with self.assertRaises(ClientDisconnected):
                server.coach_response_transport().stream_request({"model": "gpt-6-luna"}, lambda _: (_ for _ in ()).throw(ClientDisconnected()))
        self.assertEqual(
            server.provider_state_service().summary("openai")["last_operation"],
            "responses_stream_cancelled",
        )

    def test_background_chat_cancel_closes_the_active_provider_response(self):
        operation_id = "background-stream-cancel-close"
        session_key = "session-background-cancel-close"
        server.coach_job_submission_service().enqueue(
            "Eine Trainingsanfrage", "turn-background-cancel-close", session_key,
            operation_id=operation_id,
        )
        self.assertIsNotNone(server.coach_job_store().claim())
        registry = coach_streams.CHAT_STREAM_REGISTRY
        cancel_event = registry.get_background_event(operation_id)
        response = Mock()
        cancel_event._provider_response = response

        result = server.coach_cancellation_service().cancel(session_key, operation_id)

        self.assertEqual(result, {"status": "cancelling", "operation_id": operation_id})
        self.assertTrue(cancel_event.is_set())
        response.close.assert_called_once_with()
        registry.clear_state()
        restarted_event, response = registry.cancel_background_event("background-operation")
        self.assertTrue(restarted_event.is_set())
        self.assertIsNone(response)
        self.assertIs(registry.get_background_event("background-operation"), restarted_event)
        registry.remove_background_event("background-operation")
        self.assertIsNone(registry.get_background_event("background-operation"))

    def test_responses_status_and_error_payloads_are_rejected(self):
        with self.assertRaises(server.AppError) as failed:
            server.provider_state_service().validate_openai_response("/responses", {"status": "failed"})
        self.assertEqual(failed.exception.reason, "response_failed")
        with self.assertRaises(server.AppError) as unknown:
            server.provider_state_service().validate_openai_response("/responses", {"status": "mystery"})
        self.assertEqual(unknown.exception.reason, "invalid_response_status")
        with self.assertRaises(server.AppError) as error:
            server.provider_state_service().validate_openai_response(
                "/responses", {"error": {"message": "secret"}}
            )
        self.assertEqual(error.exception.reason, "response_error")

    def test_openai_request_is_not_blocked_by_local_usage_total(self):
        server.key_value_service().set("openai_usage", json.dumps({"date": server.ATHLETE_CLOCK.now().date().isoformat(), "total_tokens": 10}))
        config = replace(server.CONFIG, openai_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(server.provider_http_client(), "request", return_value={"status": "completed"}) as request:
            result = server.openai_responses_client().request("/responses", {"model": "gpt-6-luna"})
        self.assertEqual(result["status"], "completed")
        request.assert_called_once()

    def test_openai_usage_updates_are_atomic_and_tolerate_invalid_provider_counts(self):
        state = server.provider_state_service()
        threads = [
            threading.Thread(
                target=state.record_usage,
                args=("openai", {"usage": {"input_tokens": "bad", "output_tokens": 2}}, "test"),
            )
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        summary = state.summary("openai")
        self.assertEqual(summary["requests"], 8)
        self.assertEqual(summary["input_tokens"], 0)
        self.assertEqual(summary["output_tokens"], 16)

    def test_diagnostic_response_shape_keeps_only_structure(self):
        shape = server.observability.diagnostic_response_shape({"athlete_name": "Ada", "nested": [{"secret": "hidden"}], "invalid key": 1})
        self.assertEqual(shape["type"], "object")
        self.assertEqual(shape["fields"], ["athlete_name", "nested", "[nonstandard]"])
        self.assertEqual(shape["sample"], {"type": "string", "length": 3})
        self.assertNotIn("Ada", json.dumps(shape))
        self.assertEqual(server.observability.diagnostic_response_shape([{"token": "hidden"}])["item_shape"]["fields"], ["token"])

    def test_garmin_sdk_calls_log_operation_and_result_summary(self):
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        result = server.provider_http.external_call(
            "garmin",
            "get_sleep_daily",
            lambda: [{"sleepScore": 80}],
            {"window_start": "2026-08-01", "window_end": "2026-08-29"},
            logger=server.LOGGER,
            diagnostic_capture=server.DIAGNOSTIC_CAPTURE,
            operation_context=sync_observation.operation_context(),
        )
        for handler in server.LOGGER.handlers:
            handler.flush()
        entries = server.recent_log_entries_service().list()
        completed = [entry for entry in entries if entry.get("event") == "external_call_completed"][-1]
        self.assertEqual(result[0]["sleepScore"], 80)
        self.assertEqual(completed["context"]["service"], "garmin")
        self.assertEqual(completed["context"]["operation"], "get_sleep_daily")
        self.assertEqual(completed["context"]["result_items"], 1)

    def test_provider_freshness_distinguishes_never_loaded_and_stale_last_good(self):
        config = replace(
            server.CONFIG,
            intervals_api_key="fake-intervals-key",
            garmin_fixture_path="",
            garmin_email="",
            garmin_tokenstore=str(self._class_data_dir / "missing-garmin-tokens"),
            calendar_ical_url="",
        )
        with patch.object(server, "CONFIG", config):
            server.profile_service().save({"weather_location": "Berlin"})
            initial = {(item["provider"], item["area"]): item for item in server.provider_freshness_service().current(
                profile=server.profile_service().get(), garmin_has_core_error=bool(server.garmin_sync_state_service().core_error_entries()),
                garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists())}
            self.assertEqual(initial[("intervals", "activities")]["state"], "never_loaded")
            self.assertEqual(initial[("weather", "forecast")]["state"], "never_loaded")
            refresh_id = server.provider_refresh_tracker().start(
                "intervals", "activities", "operation-test", "manual"
            )
            server.provider_refresh_tracker().finish(
                refresh_id, "error", "failed", error_code="network_error"
            )
            failed = {(item["provider"], item["area"]): item for item in server.provider_freshness_service().current(
                profile=server.profile_service().get(), garmin_has_core_error=bool(server.garmin_sync_state_service().core_error_entries()),
                garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists())}
            self.assertEqual(failed[("intervals", "activities")]["state"], "error")
            self.assertEqual(failed[("intervals", "activities")]["error_code"], "network_error")
            self.assertIsNone(failed[("intervals", "activities")]["next_retry_at"])
            with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):
                unconfigured = {(item["provider"], item["area"]): item for item in server.provider_freshness_service().current(
                    profile=server.profile_service().get(), garmin_has_core_error=bool(server.garmin_sync_state_service().core_error_entries()),
                    garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists())}
            self.assertEqual(unconfigured[("intervals", "activities")]["state"], "not_configured")
            self.assertEqual(unconfigured[("intervals", "activities")]["error_code"], "network_error")
            server.sync_job_queue_service().enqueue(
                "intervals", "refresh", {"days": 1},
                requested_by="test", available_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            )
            scheduled = {(item["provider"], item["area"]): item for item in server.provider_freshness_service().current(
                profile=server.profile_service().get(), garmin_has_core_error=bool(server.garmin_sync_state_service().core_error_entries()),
                garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists())}
            self.assertTrue(scheduled[("intervals", "activities")]["next_retry_at"])
            refresh_id = server.provider_refresh_tracker().start(
                "intervals", "activities", "operation-test-2", "manual"
            )
            server.provider_refresh_tracker().finish(
                refresh_id, "success", "complete"
            )
            with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                stale_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
                db.execute(
                    "UPDATE provider_refresh_history SET started_at=?, finished_at=? WHERE id=?",
                    (stale_at, stale_at, refresh_id),
                )
            stale = {(item["provider"], item["area"]): item for item in server.provider_freshness_service().current(
                profile=server.profile_service().get(), garmin_has_core_error=bool(server.garmin_sync_state_service().core_error_entries()),
                garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists())}
            self.assertEqual(stale[("intervals", "activities")]["state"], "stale")
            self.assertTrue(stale[("intervals", "activities")]["has_last_good"])

    def test_provider_refresh_history_is_bounded_and_diagnostic_safe(self):
        for index in range(server.sync_freshness.PROVIDER_REFRESH_MAX_ROWS + 5):
            refresh_id = server.provider_refresh_tracker().start(
                "garmin", "data", f"operation-{index}", "manual"
            )
            server.provider_refresh_tracker().finish(
                refresh_id, "success", "complete"
            )
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            count = db.execute("SELECT COUNT(*) AS count FROM provider_refresh_history").fetchone()["count"]
        self.assertEqual(count, server.sync_freshness.PROVIDER_REFRESH_MAX_ROWS)
        report = server.diagnostic_report_service().report()
        self.assertIn("provider_freshness", report)
        self.assertNotIn("operation-", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
