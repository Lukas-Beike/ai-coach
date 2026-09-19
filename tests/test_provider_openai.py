import json
import threading
import unittest
from types import MappingProxyType

from backend.errors import AppError
from backend.providers.http import ProviderRequestCancelled, ProviderResponseTooLarge
from backend.providers.openai import (
    StreamReadResult,
    StreamReadState,
    consume_sse_event,
    endpoint,
    error_details,
    error_diagnostic_details,
    rate_limit_snapshot,
    read_stream_response,
    request_stream_response,
    response_failure_reason,
    response_id,
    response_text,
    responses_payload,
    retry_after_seconds,
    safe_log_reason,
)


def body(error=None):
    return json.dumps({"error": error or {}}).encode()


_UNSET = object()


class _StreamResponse:
    def __init__(self, lines, *, on_iter=None, close_event=None, status=_UNSET, code=_UNSET, headers=_UNSET):
        self._lines = iter(lines)
        self._index = 0
        self._on_iter = on_iter
        self._close_event = close_event
        self.closed = False
        if status is not _UNSET:
            self.status = status
        if code is not _UNSET:
            self.code = code
        if headers is not _UNSET:
            self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        if self._on_iter is not None:
            self._on_iter(self._index)
        self._index += 1
        return next(self._lines)

    def close(self):
        self.closed = True
        if self._close_event is not None:
            self._close_event.set()


class OpenAIProviderErrorTests(unittest.TestCase):
    def test_response_id_trims_and_accepts_ascii_boundary_values(self):
        self.assertEqual(response_id("  resp_a  "), "resp_a")
        self.assertEqual(response_id("resp_" + "a" * 200), "resp_" + "a" * 200)
        self.assertEqual(response_id("resp_a-b_9"), "resp_a-b_9")

    def test_response_id_rejects_invalid_and_non_ascii_values(self):
        for value in (
            None,
            "",
            "resp_",
            "resp_" + "a" * 201,
            "resp_ä",
            "response_a",
            "resp_a/b",
        ):
            with self.subTest(value=value), self.assertRaises(AppError) as raised:
                response_id(value)
            self.assertEqual(raised.exception.status, 502)
            self.assertEqual(raised.exception.message, "OpenAI hat keine gültige Response-ID zurückgegeben.")
            self.assertEqual(raised.exception.reason, "invalid_response")

    def test_responses_payload_removes_internal_provider_without_mutating_mapping(self):
        marker = object()
        payload = MappingProxyType({"_ai_provider": "openai", "model": "gpt-test", "marker": marker})
        result = responses_payload(payload, thinking_level="medium")
        self.assertEqual(result["model"], "gpt-test")
        self.assertIs(result["marker"], marker)
        self.assertNotIn("_ai_provider", result)
        self.assertEqual(payload["_ai_provider"], "openai")
        self.assertIsNot(result, payload)

    def test_responses_payload_defaults_reasoning_and_preserves_explicit_reasoning(self):
        self.assertEqual(
            responses_payload({"input": "hello"}, thinking_level="high")["reasoning"],
            {"effort": "high"},
        )
        explicit = {"effort": "low", "summary": "auto"}
        result = responses_payload({"reasoning": explicit}, thinking_level="high")
        self.assertIs(result["reasoning"], explicit)
        self.assertEqual(result["reasoning"], explicit)

    def test_responses_payload_forces_stream_and_background_store_flags(self):
        payload = {"stream": False, "background": False, "store": False}
        streamed = responses_payload(payload, thinking_level="medium", stream=True)
        self.assertTrue(streamed["stream"])
        self.assertFalse(streamed["background"])
        self.assertFalse(streamed["store"])

        background = responses_payload(payload, thinking_level="medium", background=True)
        self.assertFalse(background["stream"])
        self.assertTrue(background["background"])
        self.assertTrue(background["store"])
        self.assertEqual(payload, {"stream": False, "background": False, "store": False})

    def test_endpoint_joins_base_path_and_normalizes_api_path(self):
        self.assertEqual(
            endpoint("https://foundry.example.invalid/openai/v1/", "/responses", default_base_url="https://api.openai.com/v1"),
            "https://foundry.example.invalid/openai/v1/responses",
        )
        self.assertEqual(
            endpoint("https://foundry.example.invalid/openai/v1", "conversations/abc", default_base_url="https://api.openai.com/v1"),
            "https://foundry.example.invalid/openai/v1/conversations/abc",
        )

    def test_endpoint_uses_default_for_empty_base_and_rejects_unsafe_base_urls(self):
        default = "https://api.openai.com/v1"
        self.assertEqual(endpoint("", "responses", default_base_url=default), default + "/responses")
        self.assertEqual(endpoint("   ", "responses", default_base_url=default), default + "/responses")
        for invalid in (
            "https://user:password@foundry.example.invalid/openai/v1",
            "https://foundry.example.invalid/openai/v1?api-version=2024-10-21",
            "https://foundry.example.invalid/openai/v1#fragment",
            "ftp://foundry.example.invalid/openai/v1",
            "openai/v1",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AppError) as raised:
                endpoint(invalid, "responses", default_base_url=default)
            self.assertEqual(raised.exception.status, 500)

    def test_consume_sse_event_ignores_empty_and_done(self):
        deltas = []
        self.assertIsNone(consume_sse_event([], "", deltas.append))
        self.assertIsNone(consume_sse_event([" [DONE] "], "", deltas.append))
        self.assertEqual(deltas, [])

    def test_consume_sse_event_supports_multiline_json_and_deltas(self):
        deltas = []
        self.assertIsNone(
            consume_sse_event(
                ['{"type":"response.output_text.delta",', '"delta":"Hallo ☃"}'],
                "",
                deltas.append,
            )
        )
        self.assertEqual(deltas, ["Hallo ☃"])
        self.assertIsNone(consume_sse_event(['{"delta":""}'], "response.output_text.delta", deltas.append))
        self.assertEqual(deltas, ["Hallo ☃"])

    def test_consume_sse_event_reports_trimmed_response_ids(self):
        response_ids = []
        for event_name in ("response.created", "response.in_progress"):
            with self.subTest(event_name=event_name):
                self.assertIsNone(
                    consume_sse_event(
                        ['{"response":{"id":"  resp_123  "}}'],
                        event_name,
                        lambda _: None,
                        response_ids.append,
                    )
                )
        self.assertEqual(response_ids, ["resp_123", "resp_123"])

    def test_consume_sse_event_returns_all_final_response_states(self):
        for event_name in ("response.completed", "response.incomplete", "response.failed"):
            with self.subTest(event_name=event_name):
                event = {"response": {"id": "resp_123", "status": event_name.removeprefix("response.")}}
                self.assertEqual(
                    consume_sse_event([json.dumps(event)], event_name, lambda _: None),
                    event["response"],
                )

    def test_consume_sse_event_rejects_invalid_json_and_non_objects(self):
        expected_message = "OpenAI hat ein ungültiges Streaming-Ereignis zurückgegeben."
        for data_lines in (["{"], ["[]"]):
            with self.subTest(data_lines=data_lines), self.assertRaises(AppError) as raised:
                consume_sse_event(data_lines, "", lambda _: None)
            self.assertEqual(raised.exception.status, 502)
            self.assertEqual(raised.exception.message, expected_message)
            self.assertEqual(raised.exception.reason, "invalid_response")

    def test_read_stream_response_returns_final_response_deltas_ids_and_byte_count(self):
        lines = [
            b"event: response.created\n",
            b'data: {"response":{"id":"resp_123"}}\n',
            b"\n",
            b"event: response.output_text.delta\n",
            b'data: {"delta":"Hallo"}\n',
            b"\n",
            b"event: response.completed\n",
            b'data: {"response":{"id":"resp_123","status":"completed"}}\n',
            b"\n",
        ]
        deltas = []
        response_ids = []
        result = read_stream_response(
            lines,
            max_bytes=sum(map(len, lines)),
            on_text_delta=deltas.append,
            on_response_id=response_ids.append,
        )
        self.assertEqual(result, StreamReadResult({"id": "resp_123", "status": "completed"}, sum(map(len, lines))))
        self.assertEqual(deltas, ["Hallo"])
        self.assertEqual(response_ids, ["resp_123"])

    def test_read_stream_response_flushes_trailing_event_without_blank_line(self):
        lines = [
            b"event: response.output_text.delta\n",
            b'data: {"delta":"trailing"}\n',
        ]
        deltas = []
        result = read_stream_response(lines, max_bytes=1000, on_text_delta=deltas.append)
        self.assertIsNone(result.response)
        self.assertEqual(result.response_bytes, sum(map(len, lines)))
        self.assertEqual(deltas, ["trailing"])

    def test_read_stream_response_raises_before_iterating_when_cancelled(self):
        cancel_event = threading.Event()
        cancel_event.set()

        class UnreadResponse:
            def __iter__(self):
                raise AssertionError("cancelled response must not be iterated")

        with self.assertRaises(ProviderRequestCancelled):
            read_stream_response(UnreadResponse(), max_bytes=10, cancel_event=cancel_event, on_text_delta=lambda _: None)

    def test_read_stream_response_raises_when_cancelled_during_iteration(self):
        cancel_event = threading.Event()

        class CancellingResponse:
            def __init__(self):
                self._lines = iter((b"data: {\"delta\":\"first\"}\n", b"\n"))

            def __iter__(self):
                return self

            def __next__(self):
                line = next(self._lines)
                cancel_event.set()
                return line

        with self.assertRaises(ProviderRequestCancelled):
            read_stream_response(CancellingResponse(), max_bytes=1000, cancel_event=cancel_event, on_text_delta=lambda _: None)

    def test_read_stream_response_rejects_oversized_stream(self):
        state = StreamReadState()
        with self.assertRaisesRegex(ProviderResponseTooLarge, "^provider response exceeds configured size limit$"):
            read_stream_response([b"data: {}\n"], max_bytes=1, on_text_delta=lambda _: None, state=state)
        self.assertEqual(state.response_bytes, len(b"data: {}\n"))

    def test_read_stream_response_preserves_iterator_exception(self):
        failure = RuntimeError("iterator failed")

        class FailingResponse:
            def __iter__(self):
                return self

            def __next__(self):
                raise failure

        with self.assertRaises(RuntimeError) as raised:
            read_stream_response(FailingResponse(), max_bytes=1000, on_text_delta=lambda _: None)
        self.assertIs(raised.exception, failure)

    def test_request_stream_response_returns_result_without_status_or_headers(self):
        lines = [
            b"event: response.created\n",
            b'data: {"response":{"id":"resp_123"}}\n',
            b"\n",
            b"event: response.output_text.delta\n",
            b'data: {"delta":"Hallo"}\n',
            b"\n",
            b"event: response.completed\n",
            b'data: {"response":{"id":"resp_123","status":"completed"}}\n',
            b"\n",
        ]
        response = _StreamResponse(lines)
        deltas = []
        response_ids = []
        result = request_stream_response(
            object(),
            timeout=3,
            max_bytes=sum(map(len, lines)),
            on_text_delta=deltas.append,
            on_response_id=response_ids.append,
            opener=lambda request, timeout: response,
        )
        self.assertEqual(result, StreamReadResult({"id": "resp_123", "status": "completed"}, sum(map(len, lines))))
        self.assertEqual(deltas, ["Hallo"])
        self.assertEqual(response_ids, ["resp_123"])
        self.assertTrue(response.closed)

    def test_request_stream_response_records_headers_and_status_fallbacks(self):
        self.assertEqual(StreamReadState(5).response_bytes, 5)
        headers = {"x-request-id": "req_test"}
        response = _StreamResponse([b"\n"], status=202, code=203, headers=headers)
        state = StreamReadState()
        request_stream_response(
            object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
            opener=lambda *_args, **_kwargs: response, state=state,
        )
        self.assertEqual(state.status, 202)
        self.assertIs(state.headers, headers)

        for response_kwargs, expected_status in (({"code": 204}, 204), ({}, 200)):
            with self.subTest(response_kwargs=response_kwargs):
                response = _StreamResponse([b"\n"], **response_kwargs)
                state = StreamReadState()
                request_stream_response(
                    object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                    opener=lambda *_args, _response=response, **_kwargs: _response, state=state,
                )
                self.assertEqual(state.status, expected_status)
                self.assertIsNone(state.headers)

    def test_request_stream_response_cancels_header_wait_and_closes_late_response(self):
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
                request_stream_response(
                    object(),
                    timeout=3,
                    max_bytes=1000,
                    cancel_event=cancel_event,
                    on_text_delta=lambda _delta: None,
                    opener=opener,
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

    def test_request_stream_response_cancels_during_iteration_and_closes_response(self):
        cancel_event = threading.Event()
        state = StreamReadState()

        def on_iter(index):
            if index == 1:
                cancel_event.set()

        response = _StreamResponse([b": comment\n", b"data: {}\n"], on_iter=on_iter)
        with self.assertRaises(ProviderRequestCancelled):
            request_stream_response(
                object(),
                timeout=3,
                max_bytes=1000,
                cancel_event=cancel_event,
                on_text_delta=lambda _delta: None,
                opener=lambda request, timeout: response,
                state=state,
            )
        self.assertTrue(response.closed)
        self.assertEqual(state.response_bytes, len(b": comment\n"))

    def test_request_stream_response_preserves_replaced_response_handle(self):
        cancel_event = threading.Event()
        replacement = object()

        def on_iter(_index):
            cancel_event._provider_response = replacement

        response = _StreamResponse([b"data: {}\n"], on_iter=on_iter)
        request_stream_response(
            object(),
            timeout=3,
            max_bytes=1000,
            cancel_event=cancel_event,
            on_text_delta=lambda _delta: None,
            opener=lambda request, timeout: response,
        )
        self.assertIs(cancel_event._provider_response, replacement)
        self.assertTrue(response.closed)

    def test_request_stream_response_preserves_opener_exception(self):
        expected = RuntimeError("opener failed")

        def opener(_request, **_kwargs):
            raise expected

        with self.assertRaises(RuntimeError) as raised:
            request_stream_response(
                object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None, opener=opener
            )
        self.assertIs(raised.exception, expected)

    def test_request_stream_response_preserves_iterator_and_unicode_exceptions(self):
        iterator_failure = RuntimeError("iterator failed")

        class FailingResponse(_StreamResponse):
            def __next__(self):
                if self._index == 1:
                    raise iterator_failure
                return super().__next__()

        response = FailingResponse([b"data: {}\n"])
        state = StreamReadState()
        with self.assertRaises(RuntimeError) as raised:
            request_stream_response(
                object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                opener=lambda *_args, **_kwargs: response,
                state=state,
            )
        self.assertIs(raised.exception, iterator_failure)
        self.assertTrue(response.closed)
        self.assertEqual(state.response_bytes, len(b"data: {}\n"))

        unicode_response = _StreamResponse([b"data: \xff\n"])
        unicode_state = StreamReadState()
        with self.assertRaises(UnicodeDecodeError):
            request_stream_response(
                object(), timeout=3, max_bytes=1000, on_text_delta=lambda _delta: None,
                opener=lambda *_args, **_kwargs: unicode_response,
                state=unicode_state,
            )
        self.assertTrue(unicode_response.closed)
        self.assertEqual(unicode_state.response_bytes, len(b"data: \xff\n"))

    def test_request_stream_response_preserves_size_limit_and_byte_state(self):
        state = StreamReadState()
        response = _StreamResponse([b"data: {}\n"])
        with self.assertRaisesRegex(ProviderResponseTooLarge, "^provider response exceeds configured size limit$"):
            request_stream_response(
                object(),
                timeout=3,
                max_bytes=1,
                on_text_delta=lambda _delta: None,
                opener=lambda *_args, **_kwargs: response,
                state=state,
            )
        self.assertEqual(state.response_bytes, len(b"data: {}\n"))
        self.assertTrue(response.closed)

    def test_response_parsers_remain_pure(self):
        self.assertEqual(response_failure_reason("/responses", None), "invalid_response")
        self.assertEqual(response_failure_reason("/responses", {"status": "failed"}), "response_failed")
        self.assertEqual(response_failure_reason("/models", {"status": "unknown"}), None)
        self.assertEqual(response_text({"output_text": "  hello  "}), "hello")
        self.assertEqual(
            response_text({"output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]}),
            "hi",
        )

    def test_retry_after_is_numeric_bounded_ceiled_and_non_negative(self):
        self.assertEqual(retry_after_seconds({"retry-after": "12.5"}), 13)
        self.assertEqual(retry_after_seconds({"retry-after": "0"}), 1)
        self.assertEqual(retry_after_seconds({"retry-after": "86400"}), 86400)
        self.assertEqual(retry_after_seconds({"retry-after": "86400.1"}), 86400)
        for value in ("-1", "nan", "inf", "not-a-delay", None):
            self.assertIsNone(retry_after_seconds({"retry-after": value}))
        self.assertIsNone(retry_after_seconds(None))

    def test_diagnostic_details_keep_only_safe_tokens_and_bounded_bytes(self):
        raw = body(
            {
                "code": "Invalid_Function_Call_Output",
                "type": "invalid_request_error",
                "param": "input[0]",
                "message": "secret provider detail must not leak",
            }
        )
        details = error_diagnostic_details(raw, {"x-request-id": "req_test_123"}, max_response_bytes=len(raw) - 1)
        self.assertEqual(details["error_code"], "invalid_function_call_output")
        self.assertEqual(details["error_type"], "invalid_request_error")
        self.assertEqual(details["parameter"], "input[0]")
        self.assertEqual(details["request_id"], "req_test_123")
        self.assertEqual(details["error_body_bytes"], len(raw))
        self.assertNotIn("secret", json.dumps(details))

    def test_diagnostic_details_reject_malformed_and_malicious_tokens(self):
        raw = body(
            {
                "code": "x" * 161,
                "type": "type with spaces",
                "param": "input/secret",
                "message": "private provider text",
            }
        )
        details = error_diagnostic_details(raw, {"x-request-id": "request/id"}, max_response_bytes=4)
        self.assertEqual(details, {"error_body_bytes": 5})
        self.assertEqual(error_diagnostic_details(b"not-json", max_response_bytes=10), {"error_body_bytes": 8})

    def test_error_classification_preserves_status_contracts(self):
        cases = (
            (401, {}, "authentication_or_permission"),
            (403, {}, "authentication_or_permission"),
            (404, {}, "not_found"),
            (500, {}, "provider_unavailable"),
            (400, {}, "http_error"),
            (429, {}, "rate_limit_exceeded"),
            (429, {"code": "model_not_found"}, "rate_limit_exceeded"),
        )
        for status, error, reason in cases:
            with self.subTest(status=status, error=error):
                details = error_details(status, body(error), updated_at="2026-09-19T10:00:00Z")
                self.assertEqual(details["reason"], reason)
                self.assertEqual(details["updated_at"], "2026-09-19T10:00:00Z")
                self.assertNotIn("message", details["message"])

    def test_billing_and_quota_are_classified_before_429(self):
        self.assertEqual(
            error_details(429, body({"code": "credit_balance_exhausted"}), updated_at="now")["reason"],
            "credit_balance_exhausted",
        )
        for code in ("organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"):
            self.assertEqual(error_details(429, body({"code": code}), updated_at="now")["reason"], code)
        self.assertEqual(
            error_details(429, body({"type": "insufficient_quota"}), updated_at="now")["reason"],
            "insufficient_quota",
        )

    def test_conversation_lock_and_invalid_state_are_distinct(self):
        locked = error_details(409, body({"code": "conversation_locked"}), updated_at="now")
        invalid = error_details(
            400,
            body(
                {
                    "code": "invalid_function_call_output",
                    "type": "invalid_request_error",
                    "param": "input[0]",
                    "message": "secret call details",
                }
            ),
            updated_at="now",
        )
        self.assertEqual(locked["reason"], "conversation_locked")
        self.assertEqual(invalid["reason"], "conversation_state_invalid")
        self.assertNotIn("secret", json.dumps(invalid))
        for provider_message in (
            "No tool output found for function call private",
            "Item private of type reasoning was provided without its required following item.",
        ):
            with self.subTest(provider_message=provider_message):
                self.assertEqual(
                    error_details(
                        400,
                        body({"type": "invalid_request_error", "param": "input", "message": provider_message}),
                        updated_at="now",
                    )["reason"],
                    "conversation_state_invalid",
                )
        unrelated = error_details(
            400,
            body(
                {
                    "type": "invalid_request_error",
                    "param": "input",
                    "message": "Input contains an unsupported content type.",
                }
            ),
            updated_at="now",
        )
        self.assertEqual(unrelated["reason"], "http_error")

    def test_error_details_attach_retry_after_and_never_provider_text(self):
        details = error_details(
            429,
            body({"message": "private provider message", "code": "rate_limit_exceeded"}),
            {"retry-after": "1.2"},
            updated_at="now",
        )
        self.assertEqual(details["retry_after_seconds"], 2)
        self.assertNotIn("private", json.dumps(details))

    def test_safe_log_reason_is_static_allowlist(self):
        self.assertEqual(safe_log_reason("project_spend_limit_exceeded"), "usage_limit_exceeded")
        self.assertEqual(safe_log_reason("usage_limit_exceeded"), "usage_limit_exceeded")
        self.assertEqual(safe_log_reason("provider_timeout"), "provider_timeout")
        self.assertEqual(safe_log_reason("provider-private-message"), "http_error")
        self.assertEqual(safe_log_reason(None), "http_error")
        self.assertEqual(safe_log_reason({"reason": "provider_timeout"}), "http_error")

    def test_rate_limit_snapshot_is_allowlisted_and_empty_is_none(self):
        self.assertIsNone(rate_limit_snapshot({}, updated_at="now"))
        snapshot = rate_limit_snapshot(
            {
                "x-ratelimit-remaining-requests": "19",
                "x-ratelimit-reset-tokens": "30s",
                "x-request-id": "must-not-be-copied",
                "untrusted": "must-not-be-copied",
                "x-ratelimit-limit-tokens": "",
            },
            updated_at="now",
        )
        self.assertEqual(
            snapshot,
            {"updated_at": "now", "remaining_requests": "19", "reset_tokens": "30s"},
        )


if __name__ == "__main__":
    unittest.main()
