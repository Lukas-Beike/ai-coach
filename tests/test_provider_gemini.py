import json
import threading
import unittest

from backend.errors import AppError
from backend.providers.gemini import (
    StreamAccumulator,
    error_details,
    function_tools,
    input_parts,
    read_stream_response,
    request_payload,
    response_text,
)
from backend.providers.http import ProviderRequestCancelled, ProviderResponseTooLarge


class GeminiProviderErrorTests(unittest.TestCase):
    def assert_reason(self, status, body=b"{}", reason="http_error", message=None):
        details = error_details(status, body, updated_at="2026-09-19T10:11:12+00:00")
        self.assertEqual(details["reason"], reason)
        self.assertEqual(details["http_status"], status)
        self.assertEqual(details["updated_at"], "2026-09-19T10:11:12+00:00")
        self.assertEqual(details["state"], "error")
        if message is not None:
            self.assertEqual(details["message"], message)
        return details

    def test_status_classes_use_stable_reasons_and_messages(self):
        self.assert_reason(
            401,
            reason="authentication_or_permission",
            message="Der Gemini-Zugang wurde abgelehnt. Bitte API-Schlüssel und Berechtigungen prüfen.",
        )
        self.assert_reason(
            403,
            reason="authentication_or_permission",
            message="Der Gemini-Zugang wurde abgelehnt. Bitte API-Schlüssel und Berechtigungen prüfen.",
        )
        self.assert_reason(
            404,
            reason="not_found",
            message="Das konfigurierte Gemini-Modell oder der angeforderte Dienst wurde nicht gefunden.",
        )
        self.assert_reason(
            503,
            reason="provider_unavailable",
            message="Gemini ist vorübergehend nicht verfügbar. Bitte später erneut versuchen.",
        )
        self.assert_reason(
            400,
            reason="http_error",
            message="Gemini konnte die Anfrage nicht verarbeiten (HTTP 400).",
        )

    def test_permission_and_unauthenticated_detail_markers_classify_authentication(self):
        for marker in ("permissionDenied", "UNAUTHENTICATED"):
            body = json.dumps({"error": {"details": [{"reason": marker}]}}).encode()
            self.assert_reason(400, body, reason="authentication_or_permission")

    def test_quota_markers_in_status_reason_and_type_classify_quota(self):
        for error in (
            {"status": "RESOURCE_EXHAUSTED", "details": [{"reason": "quotaExceeded"}]},
            {"details": [{"reason": "quotaExceeded"}]},
            {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure"}]},
        ):
            body = json.dumps({"error": error}).encode()
            self.assert_reason(429, body, reason="insufficient_quota")

    def test_non_quota_429_is_rate_limit(self):
        self.assert_reason(429, b'{"error":{"message":"provider text"}}', reason="rate_limit_exceeded")

    def test_malformed_json_and_foreign_shapes_are_safe(self):
        for body in (
            b"not-json",
            b"",
            b"[]",
            b'{"error": "not-an-object"}',
            b'{"error": {"details": [null, "text", {"reason": ["quota"]}]}}',
        ):
            details = self.assert_reason(400, body)
            self.assertEqual(set(details), {"state", "reason", "message", "http_status", "updated_at"})

    def test_provider_text_never_reaches_result(self):
        secret = "provider-secret-do-not-return"
        body = json.dumps({
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": secret,
                "details": [{"reason": "INVALID_ARGUMENT", "message": secret}],
            }
        }).encode()
        result = self.assert_reason(400, body)
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))


class GeminiProviderAdapterTests(unittest.TestCase):
    def test_response_text_keeps_visible_text_only(self):
        result = {"candidates": [{"content": {"parts": [{"text": "Hallo"}, {"functionCall": {"name": "x"}}]}}]}
        self.assertEqual(response_text(result), "Hallo")

    def test_function_tools_translates_functions_and_ignores_invalid_entries(self):
        tools = function_tools([
            {"type": "function", "name": "save", "parameters": {"type": "object"}},
            {"type": "text"},
        ])
        self.assertEqual(tools[0]["functionDeclarations"][0]["name"], "save")
        self.assertEqual(function_tools([]), [])

    def test_input_parts_converts_text_image_and_file_without_mutating_input(self):
        request_input = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Analyse"},
                    {"type": "input_image", "image_url": "data:image/png;base64,PNG"},
                    {"type": "input_file", "file_data": "data:application/pdf;base64,PDF"},
                ],
            },
        ]
        before = json.loads(json.dumps(request_input))
        self.assertEqual(
            input_parts(request_input, {}, []),
            [
                {"text": "Analyse"},
                {"inlineData": {"mimeType": "image/png", "data": "PNG"}},
                {"inlineData": {"mimeType": "application/pdf", "data": "PDF"}},
            ],
        )
        self.assertEqual(request_input, before)

    def test_input_parts_converts_tool_outputs_and_uses_transient_media_gate(self):
        tool_input = [
            {"type": "function_call_output", "call_id": "ok", "output": '{"saved":true}'},
            {"type": "function_call_output", "call_id": "bad", "output": "not-json"},
            {"type": "function_call_output", "call_id": "list", "output": "[1, 2]"},
        ]
        parts = input_parts(tool_input, {"ok": "save"}, [{"mime": "image/png", "data": "TRANSIENT"}])
        self.assertEqual(parts[:3], [
            {"functionResponse": {"name": "save", "response": {"saved": True}}},
            {"functionResponse": {"name": "coach_tool", "response": {"error": "Tool output was not JSON."}}},
            {"functionResponse": {"name": "coach_tool", "response": {"result": [1, 2]}}},
        ])
        self.assertEqual(parts[3], {"inlineData": {"mimeType": "image/png", "data": "TRANSIENT"}})
        self.assertEqual(
            input_parts(
                [{"role": "user", "content": [{"type": "input_text", "text": "untrusted_fit_raw_base64"}]}],
                {},
                [{"mime": "image/png", "data": "IGNORED"}],
            ),
            [{"text": "untrusted_fit_raw_base64"}],
        )

    def test_request_payload_preserves_tools_choice_schema_tokens_and_thinking(self):
        payload = {
            "instructions": "Be concise",
            "max_output_tokens": 321,
            "reasoning": {"effort": "invalid"},
            "tools": [{"type": "function", "name": "save", "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "save"},
            "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
        }
        before = json.loads(json.dumps(payload))
        request = request_payload(
            payload,
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            default_max_output_tokens=999,
            default_thinking_level="medium",
            json_media_type="application/custom+json",
        )
        self.assertEqual(request["generationConfig"]["maxOutputTokens"], 321)
        self.assertEqual(request["generationConfig"]["responseMimeType"], "application/custom+json")
        self.assertEqual(request["generationConfig"]["responseJsonSchema"], {"type": "object"})
        self.assertEqual(request["generationConfig"]["thinkingConfig"], {"thinkingBudget": 8192})
        self.assertEqual(request["systemInstruction"], {"parts": [{"text": "Be concise"}]})
        self.assertEqual(request["toolConfig"], {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["save"]}})
        self.assertEqual(payload, before)

    def test_request_payload_uses_gemini_three_thinking_level_and_defaults(self):
        request = request_payload(
            {"reasoning": {"effort": "high"}},
            model="gemini-3.0-flash",
            contents=[],
            default_max_output_tokens=100,
            default_thinking_level="low",
        )
        self.assertEqual(request["generationConfig"], {
            "maxOutputTokens": 100,
            "thinkingConfig": {"thinkingLevel": "high"},
        })
        fallback = request_payload(
            {"reasoning": {"effort": "bogus"}},
            model="gemini-3.0-flash",
            contents=[],
            default_max_output_tokens=100,
            default_thinking_level="low",
        )
        self.assertEqual(fallback["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})


class GeminiStreamAccumulatorTests(unittest.TestCase):
    def accumulate(self, events):
        deltas = []
        accumulator = StreamAccumulator(deltas.append)
        for event in events:
            accumulator.consume_data_lines(event)
        return accumulator.aggregate, deltas

    def test_ignores_empty_and_done_events(self):
        aggregate, deltas = self.accumulate([[], [""], ["  "], ["[DONE]"]])
        self.assertEqual(aggregate, {"candidates": []})
        self.assertEqual(deltas, [])

    def test_multiline_json_is_decoded(self):
        aggregate, deltas = self.accumulate([["{\"candidates\":", " [{\"content\": {\"parts\": [{\"text\": \"Hallo\"}]}}]} "]])
        self.assertEqual(deltas, ["Hallo"])
        self.assertEqual(aggregate["candidates"][0]["content"]["parts"], [{"text": "Hallo"}])

    def test_metadata_and_multiple_candidates_are_preserved(self):
        aggregate, deltas = self.accumulate([[
            json.dumps({
                "modelVersion": "gemini-test",
                "promptFeedback": {"blockReason": "NONE"},
                "usageMetadata": {"totalTokenCount": 4},
                "candidates": [
                    {"finishReason": "STOP", "content": {"role": "model", "parts": [{"text": "A"}]}},
                    {"finishMessage": "second", "content": {"parts": [{"text": "B"}]}},
                ],
            }),
        ]])
        self.assertEqual(deltas, ["A"])
        self.assertEqual(aggregate["modelVersion"], "gemini-test")
        self.assertEqual(aggregate["promptFeedback"], {"blockReason": "NONE"})
        self.assertEqual(aggregate["usageMetadata"], {"totalTokenCount": 4})
        self.assertEqual(aggregate["candidates"][0]["finishReason"], "STOP")
        self.assertEqual(aggregate["candidates"][1]["finishMessage"], "second")
        self.assertEqual(aggregate["candidates"][1]["content"]["parts"], [{"text": "B"}])

    def test_text_parts_coalesce_only_when_metadata_matches(self):
        aggregate, deltas = self.accumulate([
            [json.dumps({"candidates": [{"content": {"parts": [{"text": "one", "thought": True}]}}]})],
            [json.dumps({"candidates": [{"content": {"parts": [{"text": " two", "thought": True}]}}]})],
            [json.dumps({"candidates": [{"content": {"parts": [{"text": "three", "thought": False}]}}]})],
        ])
        self.assertEqual(deltas, ["one", " two", "three"])
        self.assertEqual(aggregate["candidates"][0]["content"]["parts"], [
            {"text": "one two", "thought": True},
            {"text": "three", "thought": False},
        ])

    def test_invalid_json_and_non_objects_raise_invalid_response(self):
        for data_lines in (["not-json"], ["[]"], ["null"], ["42"]):
            with self.subTest(data_lines=data_lines):
                with self.assertRaises(AppError) as raised:
                    StreamAccumulator(lambda _delta: None).consume_data_lines(data_lines)
                self.assertEqual(raised.exception.status, 502)
                self.assertEqual(raised.exception.reason, "invalid_response")
                self.assertEqual(
                    raised.exception.message,
                    "Gemini hat ein ung\\u00fcltiges Streaming-Ereignis zur\\u00fcckgegeben.",
                )


class _StreamResponse:
    def __init__(self, lines, on_iter=None, close_event=None):
        self.lines = lines
        self.on_iter = on_iter
        self.close_event = close_event
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __iter__(self):
        for index, line in enumerate(self.lines):
            if self.on_iter is not None:
                self.on_iter(index)
            yield line

    def close(self):
        self.closed = True
        if self.close_event is not None:
            self.close_event.set()


class GeminiStreamResponseReaderTests(unittest.TestCase):
    def test_success_preserves_metadata_deltas_and_byte_count(self):
        lines = [
            b'data: {"modelVersion":"test","candidates":[{"content":{"parts":[{"text":"Hallo"}]}}]}\n',
            b"\n",
            b'data: {"usageMetadata":{"totalTokenCount":3},"candidates":[{"finishReason":"STOP"}]}\n\n',
        ]
        deltas = []
        response = _StreamResponse(lines)

        result = read_stream_response(
            object(), timeout=3, max_bytes=1000, on_text_delta=deltas.append,
            opener=lambda request, timeout: response,
        )

        self.assertEqual(result.response_bytes, sum(map(len, lines)))
        self.assertEqual(deltas, ["Hallo"])
        self.assertEqual(result.aggregate["modelVersion"], "test")
        self.assertEqual(result.aggregate["usageMetadata"], {"totalTokenCount": 3})
        self.assertEqual(result.aggregate["candidates"][0]["finishReason"], "STOP")
        self.assertTrue(response.closed)

    def test_trailing_event_is_flushed_without_blank_line(self):
        response = _StreamResponse([b'data: {"candidates":[{"content":{"parts":[{"text":"Ende"}]}}]}\n'])

        result = read_stream_response(
            object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
            opener=lambda request, timeout: response,
        )

        self.assertEqual(result.aggregate["candidates"][0]["content"]["parts"], [{"text": "Ende"}])

    def test_header_wait_cancellation_raises_and_late_opener_is_released(self):
        started = threading.Event()
        release = threading.Event()
        late_response_closed = threading.Event()
        cancel_event = threading.Event()
        captured = []
        late_response = _StreamResponse([], close_event=late_response_closed)

        def opener(request, timeout):
            started.set()
            release.wait(2)
            return late_response

        def read():
            try:
                read_stream_response(
                    object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                    cancel_event=cancel_event, opener=opener,
                )
            except Exception as exc:  # noqa: BLE001
                captured.append(exc)

        worker = threading.Thread(target=read)
        worker.start()
        self.assertTrue(started.wait(1))
        cancel_event.set()
        worker.join(1)
        release.set()
        self.assertTrue(late_response_closed.wait(1))
        worker.join(1)
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], ProviderRequestCancelled)
        self.assertTrue(late_response.closed)

    def test_cancellation_during_iteration_raises(self):
        cancel_event = threading.Event()

        def on_iter(index):
            if index == 1:
                cancel_event.set()

        response = _StreamResponse([b": comment\n", b"data: {}\n"], on_iter=on_iter)
        with self.assertRaises(ProviderRequestCancelled):
            read_stream_response(
                object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                cancel_event=cancel_event, opener=lambda request, timeout: response,
            )
        self.assertTrue(response.closed)

    def test_size_limit_uses_stable_value_error(self):
        response = _StreamResponse([b"data: {}\n"])
        with self.assertRaisesRegex(ProviderResponseTooLarge, "^provider response exceeds configured size limit$"):
            read_stream_response(
                object(), timeout=3, max_bytes=1, on_text_delta=lambda _delta: None,
                opener=lambda request, timeout: response,
            )
        self.assertTrue(response.closed)

    def test_cleanup_does_not_remove_replaced_response_handle(self):
        cancel_event = threading.Event()
        replacement = object()

        def on_iter(index):
            cancel_event._provider_response = replacement

        response = _StreamResponse([b"data: {}\n"], on_iter=on_iter)
        read_stream_response(
            object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
            cancel_event=cancel_event, opener=lambda request, timeout: response,
        )
        self.assertIs(cancel_event._provider_response, replacement)

    def test_iterator_exception_is_propagated_unchanged(self):
        expected = RuntimeError("iterator failed")

        class FailingResponse(_StreamResponse):
            def __iter__(self):
                raise expected
                yield b""  # pragma: no cover

        response = FailingResponse([])
        with self.assertRaises(RuntimeError) as raised:
            read_stream_response(
                object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                opener=lambda request, timeout: response,
            )
        self.assertIs(raised.exception, expected)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
