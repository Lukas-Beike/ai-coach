import io
import json
import threading
import unittest
from types import MappingProxyType
from unittest import mock
from urllib.error import HTTPError

from backend.errors import AppError, ClientDisconnected
from backend.providers.http import ProviderRequestCancelled, ProviderResponseTooLarge
from backend.providers.openai import (
    OpenAIResponseFailure,
    OpenAIResponsesClient,
    OpenAIStreamClient,
    OpenAIStreamConfig,
    OpenAIStreamTelemetry,
    StreamReadResult,
    StreamReadState,
    consume_sse_event,
    endpoint,
    error_details,
    error_diagnostic_details,
    poll_background_response,
    rate_limit_snapshot,
    read_stream_response,
    request_stream_response,
    request_with_conversation_retry,
    response_failure_reason,
    response_id,
    response_text,
    responses_payload,
    retry_after_seconds,
    safe_log_reason,
    validate_response,
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


class _ClientHTTP:
    def __init__(self, *responses):
        self.calls = []
        self.responses = list(responses)

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _ClientState:
    def __init__(self):
        self.validated = []
        self.usage = []

    def validate_openai_response(self, path, result):
        self.validated.append((path, result))
        return result

    def record_usage(self, provider, response, operation):
        self.usage.append((provider, response, operation))


class _ClientLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *, extra):
        self.warnings.append((message, extra))

    def info(self, message, *, extra):
        self.infos = getattr(self, "infos", [])
        self.infos.append((message, extra))

    def log(self, level, message, *, extra):
        self.logs = getattr(self, "logs", [])
        self.logs.append((level, message, extra))


class _StreamStateService:
    def __init__(self):
        self.usage = []
        self.status = []
        self.rate_limits = []

    def validate_openai_response(self, _path, result):
        return result

    def record_usage(self, *args):
        self.usage.append(args)

    def record_status(self, *args, **kwargs):
        self.status.append((args, kwargs))

    def record_rate_limits(self, headers):
        self.rate_limits.append(headers)

    def record_success(self, *args):
        self.status.append((args, {"state": "ok"}))


class _DiagnosticCapture:
    def __init__(self):
        self.events = []

    def capture(self, name, details):
        self.events.append((name, details))


class OpenAIProviderErrorTests(unittest.TestCase):
    def test_request_with_conversation_retry_returns_without_retry(self):
        calls = []

        result = request_with_conversation_retry(lambda: calls.append("request") or {"ok": True})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls, ["request"])

    def test_request_with_conversation_retry_retries_lock_with_delays_and_notification(self):
        locked = AppError(409, "locked", reason="conversation_locked")
        outcomes = iter((locked, locked, {"ok": True}))
        waits = []
        notifications = []

        def request():
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        result = request_with_conversation_retry(
            request,
            wait=waits.append,
            on_retry=lambda attempt, delay: notifications.append((attempt, delay)),
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(waits, [1, 2])
        self.assertEqual(notifications, [(1, 1), (2, 2)])

    def test_request_with_conversation_retry_reraises_non_lock_error_unchanged(self):
        error = AppError(400, "invalid", reason="conversation_state_invalid")

        with self.assertRaises(AppError) as raised:
            request_with_conversation_retry(lambda: (_ for _ in ()).throw(error), wait=self.fail)

        self.assertIs(raised.exception, error)

    def test_request_with_conversation_retry_reraises_last_lock_error_unchanged(self):
        error = AppError(409, "locked", reason="conversation_locked")
        waits = []

        with self.assertRaises(AppError) as raised:
            request_with_conversation_retry(
                lambda: (_ for _ in ()).throw(error),
                wait=waits.append,
                max_attempts=2,
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(waits, [1])

    def test_request_with_conversation_retry_cancels_before_wait_with_original_cause(self):
        error = AppError(409, "locked", reason="conversation_locked")
        waits = []

        class Event:
            def is_set(self):
                return True

            def wait(self, _delay):
                self.fail("already-cancelled event must not wait")

        with self.assertRaises(ProviderRequestCancelled) as raised:
            request_with_conversation_retry(
                lambda: (_ for _ in ()).throw(error),
                cancel_event=Event(),
                wait=waits.append,
            )

        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(waits, [])

    def test_request_with_conversation_retry_cancels_during_event_wait_with_original_cause(self):
        error = AppError(409, "locked", reason="conversation_locked")
        waits = []

        class Event:
            def __init__(self):
                self.cancelled = False

            def is_set(self):
                return self.cancelled

            def wait(self, delay):
                waits.append(delay)
                self.cancelled = True
                return True

        event = Event()
        with self.assertRaises(ProviderRequestCancelled) as raised:
            request_with_conversation_retry(
                lambda: (_ for _ in ()).throw(error),
                cancel_event=event,
                on_retry=lambda *_args: None,
            )

        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(waits, [1])

    def test_request_with_conversation_retry_requires_positive_max_attempts(self):
        for max_attempts in (0, -1):
            with self.subTest(max_attempts=max_attempts), self.assertRaises(ValueError):
                request_with_conversation_retry(lambda: {"ok": True}, max_attempts=max_attempts)

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

    def test_poll_background_response_returns_terminal_initial_response(self):
        response = {"id": " resp_initial ", "status": "completed", "output": []}
        retrieve_calls = []

        result = poll_background_response(
            response,
            retrieve=lambda response_id: retrieve_calls.append(response_id),
            cancel=lambda response_id: self.fail("terminal response must not be cancelled"),
            poll_seconds=1,
            max_seconds=5,
        )

        self.assertIs(result, response)
        self.assertEqual(retrieve_calls, [])

    def test_poll_background_response_polls_until_terminal_with_casefold_status(self):
        responses = iter((
            {"status": "IN_PROGRESS"},
            {"status": "Queued"},
            {"status": "completed", "answer": "done"},
        ))
        retrieved_ids = []
        waits = []
        clock = iter((10.0, 10.1, 10.2, 10.3))

        class Event:
            def wait(self, seconds):
                waits.append(seconds)
                return False

        result = poll_background_response(
            {"id": "resp_poll", "status": "queued"},
            retrieve=lambda response_id: (retrieved_ids.append(response_id), next(responses))[1],
            cancel=lambda _response_id: self.fail("polling must not be cancelled"),
            cancel_event=Event(),
            poll_seconds=2,
            max_seconds=5,
            monotonic=lambda: next(clock),
        )

        self.assertEqual(result, {"status": "completed", "answer": "done"})
        self.assertEqual(retrieved_ids, ["resp_poll", "resp_poll", "resp_poll"])
        self.assertEqual(waits, [2, 2, 2])

    def test_poll_background_response_cancels_before_wait(self):
        class Event:
            def wait(self, seconds):
                waits.append(seconds)
                return True

        cancelled = []
        waits = []
        with self.assertRaises(AppError) as raised:
            poll_background_response(
                {"id": "resp_cancel", "status": "in_progress"},
                retrieve=lambda _response_id: self.fail("cancelled response must not be retrieved"),
                cancel=cancelled.append,
                cancel_event=Event(),
                poll_seconds=3,
                max_seconds=5,
                monotonic=lambda: 0,
            )

        self.assertEqual(cancelled, ["resp_cancel"])
        self.assertEqual(waits, [3])
        self.assertEqual((raised.exception.status, raised.exception.reason, raised.exception.message), (499, "chat_cancelled", "Die Coach-Anfrage wurde abgebrochen."))

    def test_poll_background_response_cancels_when_event_is_set_after_wait(self):
        class Event:
            def __init__(self):
                self.set = False

            def wait(self, seconds):
                waits.append(seconds)
                self.set = True
                return False

            def is_set(self):
                return self.set

        cancelled = []
        waits = []
        with self.assertRaises(AppError) as raised:
            poll_background_response(
                {"id": "resp_cancel_after_wait", "status": "queued"},
                retrieve=lambda _response_id: self.fail("cancelled response must not be retrieved"),
                cancel=cancelled.append,
                cancel_event=Event(),
                poll_seconds=3,
                max_seconds=5,
                monotonic=lambda: 0,
            )

        self.assertEqual(cancelled, ["resp_cancel_after_wait"])
        self.assertEqual(waits, [3])
        self.assertEqual(raised.exception.reason, "chat_cancelled")

    def test_poll_background_response_times_out_from_function_entry(self):
        times = iter((100.0, 101.0))
        cancelled = []
        sleeps = []

        with mock.patch("backend.providers.openai.time.sleep", sleeps.append), self.assertRaises(AppError) as raised:
            poll_background_response(
                {"id": "resp_timeout", "status": "queued"},
                retrieve=lambda _response_id: self.fail("timed out response must not be retrieved"),
                cancel=cancelled.append,
                poll_seconds=1,
                max_seconds=1,
                monotonic=lambda: next(times),
            )

        self.assertEqual(sleeps, [1])
        self.assertEqual(cancelled, ["resp_timeout"])
        self.assertEqual((raised.exception.status, raised.exception.reason, raised.exception.message), (504, "provider_timeout", "Die Hintergrundplanung hat das Zeitlimit überschritten."))

    def test_poll_background_response_preserves_timeout_when_cancel_fails(self):
        def cancel(_response_id):
            raise RuntimeError("remote cancellation failed")

        with mock.patch("backend.providers.openai.time.sleep"), self.assertRaises(AppError) as raised:
            poll_background_response(
                {"id": "resp_cancel_failure", "status": "queued"},
                retrieve=lambda _response_id: self.fail("timed out response must not be retrieved"),
                cancel=cancel,
                poll_seconds=1,
                max_seconds=0,
                monotonic=lambda: 1,
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (504, "provider_timeout"))

    def test_poll_background_response_rejects_invalid_initial_response_id(self):
        with self.assertRaises(AppError) as raised:
            poll_background_response(
                {"id": "not-a-response-id", "status": "completed"},
                retrieve=lambda _response_id: self.fail("invalid response must not be retrieved"),
                cancel=lambda _response_id: self.fail("invalid response must not be cancelled"),
                poll_seconds=1,
                max_seconds=5,
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (502, "invalid_response"))

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

    def test_validate_response_returns_valid_results_unchanged(self):
        result = {"status": "completed", "output_text": "hello"}
        self.assertIs(validate_response("/responses", result), result)
        non_responses_result = {"status": "unknown"}
        self.assertIs(validate_response("/models", non_responses_result), non_responses_result)

    def test_validate_response_rejects_wire_failures_with_safe_messages(self):
        cases = (
            ("/responses", None, "invalid_response", "OpenAI response is not a JSON object."),
            (
                "/responses",
                {"error": {"code": "invalid_request_error", "message": "private provider detail"}},
                "response_error",
                "OpenAI returned an error response.",
            ),
            ("/responses", {"status": "failed"}, "response_failed", "OpenAI did not complete the coach response."),
            (
                "/responses",
                {"status": "unexpected"},
                "invalid_response_status",
                "OpenAI returned an unknown response status.",
            ),
        )
        for path, result, reason, message in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(OpenAIResponseFailure) as raised:
                    validate_response(path, result)
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(raised.exception.message, message)
                self.assertEqual(str(raised.exception), message)
                self.assertIsNone(raised.exception.provider_error_code)
                self.assertNotIn("private provider detail", str(raised.exception))

    def test_validate_response_allows_only_allowlisted_error_codes(self):
        allowed_result = {"error": {"code": "known_code", "message": "private provider detail"}}
        with self.assertRaises(OpenAIResponseFailure) as raised:
            validate_response("/responses", allowed_result, allowed_error_codes=("known_code",))
        self.assertEqual(raised.exception.provider_error_code, "known_code")
        self.assertNotIn("private provider detail", str(raised.exception))

        for untrusted_code in ("other_code", 123, {"nested": "code"}):
            with self.subTest(code=untrusted_code):
                result = {"error": {"code": untrusted_code, "message": "private provider detail"}}
                with self.assertRaises(OpenAIResponseFailure) as raised:
                    validate_response("/responses", result, allowed_error_codes=("known_code",))
                self.assertIsNone(raised.exception.provider_error_code)
                self.assertNotIn("private provider detail", str(raised.exception))

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

    def _client(self, http, state=None, logger=None, **overrides):
        settings = {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1/",
            "default_base_url": "https://api.openai.com/v1",
            "responses_path": "/responses",
            "response_timeout_seconds": 17,
            "background_poll_seconds": 2,
            "background_max_seconds": 10,
            "thinking_level": lambda: "high",
            "http_client": http,
            "provider_state": state or _ClientState(),
            "logger": logger or _ClientLogger(),
        }
        settings.update(overrides)
        settings.setdefault("wait", lambda _seconds: None)
        settings.setdefault("monotonic", lambda: 0.0)
        return OpenAIResponsesClient(**settings)

    def test_responses_client_request_builds_wire_request_and_records_usage_once(self):
        state = _ClientState()
        http = _ClientHTTP({"status": "completed"})
        client = self._client(http, state)
        payload = {"input": "hello", "_ai_provider": "openai"}

        result = client.request("/responses", payload)

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(payload, {"input": "hello", "_ai_provider": "openai"})
        args, kwargs = http.calls[0]
        self.assertEqual(args[:2], ("POST", "https://api.example.test/v1/responses"))
        self.assertEqual(args[2], {"input": "hello", "reasoning": {"effort": "high"}})
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer sk-test"})
        self.assertEqual(kwargs["timeout"], 17)
        self.assertEqual(state.usage, [("openai", result, "responses")])

    def test_responses_client_requires_api_key(self):
        client = self._client(_ClientHTTP({"status": "completed"}), api_key=None)

        with self.assertRaises(AppError) as raised:
            client.request("/models", {})

        self.assertEqual((raised.exception.status, raised.exception.message), (503, "OPENAI_API_KEY ist nicht konfiguriert."))

    def test_responses_client_retries_locked_conversation_with_injected_wait(self):
        state = _ClientState()
        logger = _ClientLogger()
        waits = []
        locked = AppError(409, "locked", reason="conversation_locked")
        http = _ClientHTTP(locked, {"status": "completed"})
        client = self._client(http, state, logger, wait=waits.append)

        result = client.responses({"input": "hello"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(waits, [1])
        self.assertEqual(logger.warnings[0][1], {
            "event": "openai_conversation_locked",
            "context": {"attempt": 1, "retry_in_seconds": 1},
        })
        self.assertEqual(len(state.usage), 1)

    def test_responses_client_background_lock_backoff_returns_public_cancel_error(self):
        locked = AppError(409, "locked", reason="conversation_locked")
        http = _ClientHTTP(locked, {"id": "resp_never_created", "status": "queued"})
        client = self._client(http)

        class Event:
            def __init__(self):
                self.cancelled = False

            def is_set(self):
                return self.cancelled

            def wait(self, _seconds):
                self.cancelled = True
                return True

        with self.assertRaises(AppError) as raised:
            client.background({"input": "hello"}, cancel_event=Event())

        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))
        self.assertEqual(len(http.calls), 1)

    def test_responses_client_retrieve_validates_without_recording_usage(self):
        state = _ClientState()
        http = _ClientHTTP({"id": "resp_a", "status": "completed"})
        client = self._client(http, state)

        result = client.retrieve(" resp_a ")

        self.assertEqual(result["id"], "resp_a")
        self.assertEqual(http.calls[0][0][:2], ("GET", "https://api.example.test/v1/responses/resp_a"))
        self.assertEqual(state.usage, [])
        with self.assertRaises(AppError):
            client.retrieve("not-a-response-id")

    def test_responses_client_cancel_is_best_effort_and_logs_static_event(self):
        logger = _ClientLogger()
        http = _ClientHTTP(RuntimeError("provider detail must not be logged"))
        client = self._client(http, logger=logger)

        client.cancel("resp_a")

        self.assertEqual(logger.warnings, [(
            "OpenAI background response cancellation failed",
            {"event": "openai_background_cancel_failed"},
        )])
        self.assertNotIn("resp_a", repr(logger.warnings))

    def test_responses_client_background_records_usage_after_final_retrieve_and_notifies_once(self):
        state = _ClientState()
        http = _ClientHTTP(
            {"id": "resp_bg", "status": "queued"},
            {"id": "resp_bg", "status": "completed", "output_text": "done"},
        )
        notified = []
        waits = []
        client = self._client(http, state, wait=waits.append)

        result = client.background({"input": "hello"}, on_response_id=notified.append)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(notified, ["resp_bg"])
        self.assertEqual(waits, [2])
        self.assertEqual([entry[2] for entry in state.usage], ["responses_background"])
        self.assertEqual(len(state.usage), 1)

    def test_responses_client_background_deadline_includes_resume_retrieve(self):
        state = _ClientState()
        http = _ClientHTTP(
            {"id": "resp_bg", "status": "queued"},
            {},
        )
        times = iter((0.0, 11.0, 11.0, 11.0))
        waits = []
        client = self._client(
            http,
            state,
            wait=waits.append,
            monotonic=lambda: next(times),
        )

        with self.assertRaises(AppError) as raised:
            client.background({}, response_id="resp_bg")

        self.assertEqual((raised.exception.status, raised.exception.reason), (504, "provider_timeout"))
        self.assertEqual(waits, [2])
        self.assertEqual(http.calls[-1][0][:2], ("POST", "https://api.example.test/v1/responses/resp_bg/cancel"))
        self.assertEqual(state.usage, [])

    def _stream_client(self, opener, *, state=None, capture=None, logger=None, wait=None, **overrides):
        settings = {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1/",
            "default_base_url": "https://api.openai.com/v1",
            "responses_path": "/responses",
            "response_timeout_seconds": 17,
            "max_response_bytes": 10000,
            "app_version": "test-version",
            "json_media_type": "application/json",
            "thinking_level": lambda: "high",
            "provider_state": state or _StreamStateService(),
            "diagnostic_capture": capture or _DiagnosticCapture(),
            "logger": logger or _ClientLogger(),
            "opener": opener,
            "clock": lambda: 0.0,
            "wait": wait or (lambda _seconds: None),
            "now": lambda: "2026-09-20T10:00:00Z",
        }
        settings.update(overrides)
        config = OpenAIStreamConfig(
            api_key=settings["api_key"],
            base_url=settings["base_url"],
            default_base_url=settings["default_base_url"],
            responses_path=settings["responses_path"],
            timeout=settings["response_timeout_seconds"],
            max_bytes=settings["max_response_bytes"],
            app_version=settings["app_version"],
            media_type=settings["json_media_type"],
        )
        telemetry = OpenAIStreamTelemetry(
            settings["provider_state"],
            settings["diagnostic_capture"],
            settings["logger"],
            settings["clock"],
            settings["now"],
        )
        return OpenAIStreamClient(
            config,
            telemetry,
            settings["thinking_level"],
            settings["opener"],
            settings["wait"],
        )

    @staticmethod
    def _stream_lines(response_id="resp_test"):
        return [
            b'event: response.created\n',
            f'data: {{"type":"response.created","response":{{"id":"{response_id}"}}}}\n'.encode(),
            b"\n",
            b"event: response.output_text.delta\n",
            b'data: {"type":"response.output_text.delta","delta":"hello"}\n',
            b"\n",
            b"event: response.completed\n",
            f'data: {{"type":"response.completed","response":{{"id":"{response_id}","status":"completed","output_text":"hello","usage":{{"total_tokens":1}}}}}}\n'.encode(),
            b"\n",
        ]

    def test_stream_client_success_keeps_payload_immutable_and_wires_request(self):
        opened = []

        def opener(request, **kwargs):
            opened.append((request, kwargs))
            return _StreamResponse(
                self._stream_lines(),
                status=200,
                headers={"x-ratelimit-remaining-requests": "3"},
            )

        state = _StreamStateService()
        client = self._stream_client(opener, state=state)
        payload = {"input": "hello", "stream": False, "_ai_provider": "openai"}
        deltas = []
        response_ids = []

        result = client.stream(payload, deltas.append, on_response_id=response_ids.append)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(deltas, ["hello"])
        self.assertEqual(response_ids, ["resp_test"])
        self.assertEqual(payload, {"input": "hello", "stream": False, "_ai_provider": "openai"})
        request, kwargs = opened[0]
        self.assertEqual(request.full_url, "https://api.example.test/v1/responses")
        self.assertEqual(json.loads(request.data), {"input": "hello", "reasoning": {"effort": "high"}, "stream": True})
        self.assertEqual(request.headers["Accept"], "text/event-stream")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["timeout"], 17)
        self.assertEqual(len(state.usage), 1)

    def test_stream_client_saves_final_response_before_post_read_cancellation(self):
        cancel_event = threading.Event()
        state = _StreamStateService()
        response = _StreamResponse(self._stream_lines(), close_event=cancel_event)
        client = self._stream_client(lambda *_args, **_kwargs: response, state=state)

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None, cancel_event=cancel_event)

        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))
        self.assertEqual(state.usage, [])

    def test_stream_client_redacts_callback_app_error_from_logs_and_diagnostics(self):
        state = _StreamStateService()
        capture = _DiagnosticCapture()
        logger = _ClientLogger()
        expected = AppError(418, "private provider message", reason="private_provider_reason")
        response = _StreamResponse(self._stream_lines())
        client = self._stream_client(
            lambda *_args, **_kwargs: response,
            state=state,
            capture=capture,
            logger=logger,
        )

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: (_ for _ in ()).throw(expected))

        self.assertIs(raised.exception, expected)
        output = repr((logger.infos, logger.logs, capture.events))
        self.assertNotIn("private provider", output)
        self.assertNotIn("private_provider_reason", output)
        self.assertIn("http_error", output)

    def test_stream_client_retries_locked_conversation_with_one_second_wait(self):
        locked = HTTPError(
            "https://api.example.test/v1/responses",
            409,
            "locked",
            {},
            io.BytesIO(body({"code": "conversation_locked"})),
        )
        responses = iter((locked, _StreamResponse(self._stream_lines())))
        waits = []

        def opener(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        client = self._stream_client(opener, wait=waits.append)

        result = client.stream({"input": "hello"}, lambda _delta: None)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(waits, [1])

    def test_stream_client_cancellation_before_headers_is_public_499(self):
        cancel_event = threading.Event()
        cancel_event.set()
        opened = []
        state = _StreamStateService()
        client = self._stream_client(lambda *args, **kwargs: opened.append(args) or _StreamResponse([]), state=state)

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None, cancel_event=cancel_event)

        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))
        self.assertEqual(opened, [])
        self.assertEqual(len(state.usage), 1)

    def test_stream_client_cancellation_during_lock_backoff_records_usage_once(self):
        class CancelDuringWait:
            def __init__(self):
                self.cancelled = False

            def is_set(self):
                return self.cancelled

            def wait(self, _seconds):
                self.cancelled = True
                return True

        event = CancelDuringWait()
        state = _StreamStateService()

        def wait(_seconds):
            event.set()

        def opener(*_args, **_kwargs):
            raise HTTPError(
                "https://api.example.test/v1/responses",
                409,
                "locked",
                {},
                io.BytesIO(body({"code": "conversation_locked"})),
            )

        client = self._stream_client(opener, state=state, wait=wait)
        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None, cancel_event=event)

        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))
        self.assertEqual(len(state.usage), 1)

    def test_stream_client_preserves_headers_on_late_size_failure(self):
        state = _StreamStateService()
        response = _StreamResponse(
            [b"data: {}\n"],
            status=200,
            headers={"x-ratelimit-remaining-requests": "2"},
        )
        client = self._stream_client(lambda *_args, **_kwargs: response, state=state, max_response_bytes=1)

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None)

        self.assertEqual((raised.exception.status, raised.exception.reason), (502, "response_too_large"))
        self.assertEqual(state.rate_limits, [{"x-ratelimit-remaining-requests": "2"}])
        self.assertEqual(state.usage, [])

    def test_stream_client_http_error_keeps_retry_after_and_redacts_diagnostics(self):
        secret = "private provider text sk-test-secret"
        error = HTTPError(
            "https://api.example.test/v1/responses",
            429,
            "rate limited",
            {"retry-after": "1.2", "x-request-id": "req_test"},
            io.BytesIO(json.dumps({"error": {"code": "rate_limit_exceeded", "message": secret}}).encode()),
        )
        state = _StreamStateService()
        capture = _DiagnosticCapture()
        def opener(*_args, **_kwargs):
            raise error

        client = self._stream_client(opener, state=state, capture=capture)

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None)

        self.assertEqual((raised.exception.status, raised.exception.reason), (429, "rate_limit_exceeded"))
        self.assertEqual(raised.exception.retry_after_seconds, 2)
        self.assertNotIn("private", repr(capture.events))
        self.assertNotIn("sk-test-secret", repr(capture.events))
        self.assertEqual(state.rate_limits, [{"retry-after": "1.2", "x-request-id": "req_test"}])

    def test_stream_client_requires_final_response_and_records_usage_once_on_success(self):
        state = _StreamStateService()
        incomplete = _StreamResponse([b'data: {"type":"response.output_text.delta","delta":"hello"}\n', b"\n"])
        client = self._stream_client(lambda *_args, **_kwargs: incomplete, state=state)

        with self.assertRaises(AppError) as raised:
            client.stream({"input": "hello"}, lambda _delta: None)

        self.assertEqual((raised.exception.status, raised.exception.reason), (502, "invalid_response"))
        self.assertEqual(state.usage, [])

    def test_stream_client_timeout_network_and_client_disconnect_contracts(self):
        for failure, status, reason in (
            (TimeoutError("private timeout"), 504, "provider_timeout"),
            (OSError("private network"), 503, "provider_unavailable"),
        ):
            with self.subTest(reason=reason):
                state = _StreamStateService()
                client = self._stream_client(
                    lambda *_args, failure=failure, **_kwargs: (_ for _ in ()).throw(failure),
                    state=state,
                )
                with self.assertRaises(AppError) as raised:
                    client.stream({"input": "hello"}, lambda _delta: None)
                self.assertEqual((raised.exception.status, raised.exception.reason), (status, reason))
                self.assertEqual(state.usage, [])

        disconnect = _StreamResponse(self._stream_lines())
        state = _StreamStateService()
        client = self._stream_client(lambda *_args, **_kwargs: disconnect, state=state)
        with self.assertRaises(ClientDisconnected):
            client.stream({"input": "hello"}, lambda _delta: (_ for _ in ()).throw(ClientDisconnected()))
        self.assertEqual(len(state.usage), 1)


if __name__ == "__main__":
    unittest.main()
