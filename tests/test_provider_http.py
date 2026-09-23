import threading
import unittest
from urllib.error import HTTPError

from backend.errors import AppError
from backend.providers.http import (
    JsonHttpClient,
    JsonResponse,
    ProviderInvalidResponse,
    ProviderRequestCancelled,
    ProviderResponseTooLarge,
    error_detail,
    external_call,
    json_request_parts,
    multipart_form_data,
    open_interruptibly,
    read_bounded_response,
    read_error_body,
    read_response,
    request_body,
    request_json,
)


class _CallLogger:
    def __init__(self):
        self.records = []

    def info(self, message, **kwargs):
        self.records.append(("info", message, kwargs))

    def warning(self, message, **kwargs):
        self.records.append(("warning", message, kwargs))

    def exception(self, message, **kwargs):
        self.records.append(("exception", message, kwargs))


class _DiagnosticCapture:
    def __init__(self):
        self.entries = []

    def capture(self, event, details):
        self.entries.append((event, details))


class _ProviderState:
    def __init__(self):
        self.calls = []

    def record_rate_limits(self, headers):
        self.calls.append(("rate_limits", headers))

    def record_success(self, provider, status):
        self.calls.append(("success", provider, status))

    def record_status(self, provider, **details):
        self.calls.append(("status", provider, details))


class _JSONResponse:
    def __init__(self, body, *, status=None, code=None, headers=None):
        self.body = body
        self.closed = False
        self.close_count = 0
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        self.headers = headers if headers is not None else {"X-Test": "yes"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def read(self, _size):
        return self.body

    def close(self):
        self.closed = True
        self.close_count += 1


class ProviderHTTPTests(unittest.TestCase):
    def _client(self, opener, *, state=None, max_bytes=100, redact=None, operation_context=None):
        return JsonHttpClient(
            "1.2.3",
            max_bytes,
            self.logger,
            self.capture,
            state or _ProviderState(),
            redact or (lambda value: str(value).replace("secret", "[REDACTED]")),
            lambda headers: {
                str(key).casefold(): str(value)
                for key, value in (headers or {}).items()
                if str(key).casefold() in {"content-type", "retry-after"}
            },
            lambda: "2026-09-19T00:00:00+00:00",
            operation_context or (lambda: {"operation_id": "op-1", "trigger": "test"}),
            opener=opener,
            monotonic=lambda: 1.0,
        )

    def setUp(self):
        self.logger = _CallLogger()
        self.capture = _DiagnosticCapture()

    def test_json_http_client_success_empty_body_and_observation(self):
        state = _ProviderState()
        response = _JSONResponse(b"", status=204, headers={"Content-Type": "application/json"})
        client = self._client(lambda _request, *, timeout: response, state=state)

        self.assertIsNone(client.request("GET", "https://example.test/api/v1/resource", service="openai"))
        self.assertTrue(response.closed)
        self.assertEqual(state.calls, [
            ("rate_limits", response.headers),
            ("success", "openai", 204),
        ])
        self.assertEqual([entry[0] for entry in self.capture.entries], [
            "external_http_started", "external_http_completed",
        ])
        self.assertEqual(
            [record[2]["extra"]["event"] for record in self.logger.records],
            ["external_request_started", "external_request_completed"],
        )

    def test_json_http_client_reads_current_operation_context_for_each_request(self):
        context = {"operation_id": "op-1", "trigger": "first"}
        client = self._client(
            lambda _request, *, timeout: _JSONResponse(b"{}"),
            operation_context=lambda: context,
        )

        client.request("GET", "https://example.test/api/v1/first")
        context.update(operation_id="op-2", trigger="second")
        client.request("GET", "https://example.test/api/v1/second")

        started = [record[2]["extra"]["context"] for record in self.logger.records if record[2]["extra"]["event"] == "external_request_started"]
        self.assertEqual(
            [(entry["operation_id"], entry["trigger"]) for entry in started],
            [("op-1", "first"), ("op-2", "second")],
        )

    def test_json_http_client_classifies_openai_http_error_and_retry_after(self):
        state = _ProviderState()
        body = _JSONResponse(b'{"error":{"code":"rate_limit_exceeded"}}')
        error = HTTPError("https://api.openai.com/v1/responses", 429, "secret provider text", {"retry-after": "7"}, body)
        client = self._client(lambda _request, *, timeout: (_ for _ in ()).throw(error), state=state)

        with self.assertRaises(AppError) as raised:
            client.request("POST", "https://api.openai.com/v1/responses", payload={"secret": "payload"}, service="openai")
        self.assertEqual((raised.exception.status, raised.exception.reason), (429, "rate_limit_exceeded"))
        self.assertEqual(raised.exception.retry_after_seconds, 7)
        self.assertIs(raised.exception.__cause__, error)
        self.assertTrue(body.closed)
        self.assertIn(("rate_limits", error.headers), state.calls)
        self.assertNotIn("secret provider text", repr(self.logger.records))
        self.assertNotIn("payload", repr(self.capture.entries))

    def test_json_http_client_classifies_gemini_and_intervals_http_errors(self):
        gemini_body = _JSONResponse(b'{"error":{"status":"INTERNAL"}}')
        gemini_error = HTTPError("https://generativelanguage.googleapis.com", 500, "failure", {}, gemini_body)
        gemini_state = _ProviderState()
        with self.assertRaises(AppError) as gemini_raised:
            self._client(lambda _request, *, timeout: (_ for _ in ()).throw(gemini_error), state=gemini_state).request(
                "POST", "https://generativelanguage.googleapis.com/v1beta/models/test", service="gemini"
            )
        self.assertEqual((gemini_raised.exception.status, gemini_raised.exception.reason), (500, "provider_unavailable"))
        self.assertTrue(gemini_body.closed)
        self.assertTrue(any(call[0:2] == ("status", "gemini") for call in gemini_state.calls))

        intervals_body = _JSONResponse(b'{"error":{"message":"secret validation detail"}}')
        intervals_error = HTTPError("https://intervals.icu", 400, "failure", {}, intervals_body)
        with self.assertRaises(AppError) as intervals_raised:
            self._client(lambda _request, *, timeout: (_ for _ in ()).throw(intervals_error)).request(
                "POST", "https://intervals.icu/api/v1/workouts", service="intervals"
            )
        self.assertEqual(intervals_raised.exception.status, 502)
        self.assertIn("Intervals.icu weist die Anfrage zurück (400)", intervals_raised.exception.message)
        self.assertNotIn("secret validation detail", intervals_raised.exception.message)
        self.assertTrue(intervals_body.closed)

    def test_json_http_client_cancellation_and_cleanup(self):
        cancel_event = threading.Event()
        client = self._client(lambda *_args, **_kwargs: self.fail("opener must not run"))
        cancel_event.set()
        with self.assertRaisesRegex(AppError, "Coach-Anfrage wurde abgebrochen") as raised:
            client.request("GET", "https://example.test/api/v1/resource", cancel_event=cancel_event)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertEqual(self.capture.entries[-1][0], "external_http_failed")

        cancel_event = threading.Event()
        class CancellingResponse(_JSONResponse):
            def read(self, size):
                cancel_event.set()
                return super().read(size)

        response = CancellingResponse(b"{}")
        with self.assertRaises(AppError) as read_raised:
            self._client(lambda _request, *, timeout: response).request(
                "GET", "https://example.test/api/v1/resource", cancel_event=cancel_event
            )
        self.assertEqual(read_raised.exception.reason, "chat_cancelled")
        self.assertTrue(response.closed)

        cancel_event = threading.Event()

        class CancellingOnClose(_JSONResponse):
            def __exit__(self, *args):
                cancel_event.set()
                return super().__exit__(*args)

        response = CancellingOnClose(b"{}")
        with self.assertRaises(AppError) as close_raised:
            self._client(lambda _request, *, timeout: response).request(
                "GET", "https://example.test/api/v1/resource", cancel_event=cancel_event
            )
        self.assertEqual(close_raised.exception.reason, "chat_cancelled")
        self.assertTrue(response.closed)

        cancel_event = threading.Event()

        class CancellingErrorBody(_JSONResponse):
            def read(self, size):
                cancel_event.set()
                return super().read(size)

        error_body = CancellingErrorBody(b'{"error":"failure"}')
        error = HTTPError("https://example.test", 400, "failure", {}, error_body)
        with self.assertRaises(AppError) as error_raised:
            self._client(lambda _request, *, timeout: (_ for _ in ()).throw(error)).request(
                "GET", "https://example.test/api/v1/resource", service="intervals", cancel_event=cancel_event
            )
        self.assertEqual(error_raised.exception.reason, "chat_cancelled")
        self.assertTrue(error_body.closed)

    def test_json_http_client_maps_size_invalid_network_and_client_errors(self):
        oversized = _JSONResponse(b"1234")
        with self.assertRaises(AppError) as too_large:
            self._client(lambda _request, *, timeout: oversized, max_bytes=3).request(
                "GET", "https://example.test/api/v1/resource"
            )
        self.assertEqual(too_large.exception.status, 502)
        self.assertIsInstance(too_large.exception.__cause__, ProviderResponseTooLarge)
        self.assertTrue(oversized.closed)

        invalid = _JSONResponse(b"not-json")
        with self.assertRaises(AppError) as invalid_raised:
            self._client(lambda _request, *, timeout: invalid).request(
                "GET", "https://example.test/api/v1/resource"
            )
        self.assertEqual(invalid_raised.exception.reason, "provider_client_error")
        self.assertIsInstance(invalid_raised.exception.__cause__, ProviderInvalidResponse)
        self.assertTrue(invalid.closed)

        network = OSError("secret network detail" + "x" * 600)
        with self.assertRaises(AppError) as network_raised:
            self._client(
                lambda _request, *, timeout: (_ for _ in ()).throw(network),
                redact=lambda value: value.replace("secret", "[REDACTED]"),
            ).request(
                "GET", "https://example.test/api/v1/resource"
            )
        self.assertEqual(network_raised.exception.reason, "provider_network_error")
        self.assertIs(network_raised.exception.__cause__, network)
        network_log = next(record for record in self.logger.records if record[2]["extra"]["event"] == "upstream_network_error")
        network_detail = network_log[2]["extra"]["context"]["error"]
        self.assertIn("[REDACTED]", network_detail)
        self.assertNotIn("secret", network_detail)
        self.assertEqual(len(network_detail), 500)
        self.assertNotIn("exc_info", network_log[2])

        client_error = RuntimeError("secret client detail" + "x" * 600)
        with self.assertRaises(AppError) as client_raised:
            self._client(
                lambda _request, *, timeout: (_ for _ in ()).throw(client_error),
                redact=lambda value: value.replace("secret", "[REDACTED]"),
            ).request(
                "GET", "https://example.test/api/v1/resource"
            )
        self.assertEqual(client_raised.exception.reason, "provider_client_error")
        self.assertIs(client_raised.exception.__cause__, client_error)
        client_log = [record for record in self.logger.records if record[2]["extra"]["event"] == "external_request_failed"][-1]
        client_detail = client_log[2]["extra"]["context"]["error"]
        self.assertIn("[REDACTED]", client_detail)
        self.assertNotIn("secret", client_detail)
        self.assertEqual(len(client_detail), 500)
        self.assertNotIn("exc_info", client_log[2])

    def test_json_http_client_does_not_log_url_userinfo_or_payload(self):
        client = self._client(lambda _request, *, timeout: _JSONResponse(b'{"ok":true}'))
        client.request(
            "POST",
            "https://user:secret@example.test/api/v1/resource?token=secret",
            payload={"credential": "secret"},
        )
        rendered = repr((self.logger.records, self.capture.entries))
        self.assertNotIn("user:secret", rendered)
        self.assertNotIn('"credential": "secret"', rendered)
        self.assertNotIn("?token=secret", rendered)
    def test_request_json_decodes_object_array_scalar_and_empty_body(self):
        cases = (
            (b'{"answer": 42}', {"answer": 42}),
            (b'[1, "two"]', [1, "two"]),
            (b'false', False),
            (b'', {}),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                response = _JSONResponse(body)
                result = request_json(
                    "request",
                    timeout=12,
                    max_bytes=100,
                    opener=lambda _request, *, timeout, response=response: response,
                )
                self.assertIsInstance(result, JsonResponse)
                self.assertEqual(result.payload, expected)
                self.assertEqual(result.response_bytes, len(body))
                self.assertEqual(result.headers, response.headers)
                self.assertTrue(response.closed)
                self.assertEqual(response.close_count, 1)

    def test_request_json_normalizes_status_code_and_default(self):
        cases = (
            (_JSONResponse(b"{}", status=201, code=202), 201),
            (_JSONResponse(b"{}", code=202), 202),
            (_JSONResponse(b"{}"), 200),
        )
        for response, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                result = request_json(
                    "request",
                    timeout=12,
                    max_bytes=100,
                    opener=lambda _request, *, timeout, response=response: response,
                )
                self.assertEqual(result.status, expected_status)

    def test_request_json_rejects_invalid_utf8_and_json_with_static_message(self):
        for body in (b"\xff", b'{"secret":"do-not-leak"} trailing'):
            with self.subTest(body=body):
                response = _JSONResponse(body)
                with self.assertRaises(ProviderInvalidResponse) as context:
                    request_json(
                        "request",
                        timeout=12,
                        max_bytes=100,
                        opener=lambda _request, *, timeout, response=response: response,
                    )
                self.assertEqual(str(context.exception), "provider response is not valid UTF-8 JSON")
                self.assertNotIn("do-not-leak", str(context.exception))
                self.assertNotIn(body.decode("utf-8", errors="replace"), str(context.exception))
                self.assertTrue(response.closed)
                self.assertEqual(response.close_count, 1)

    def test_request_json_preserves_opener_errors(self):
        for expected in (
            HTTPError("https://example.test", 503, "provider failure", {}, None),
            OSError("opener failure"),
            TimeoutError("opener timeout"),
            ProviderRequestCancelled(),
        ):
            with self.subTest(error=type(expected).__name__):
                def opener(_request, *, timeout, error=expected):
                    raise error

                with self.assertRaises(type(expected)) as context:
                    request_json("request", timeout=12, max_bytes=100, opener=opener)
                self.assertIs(context.exception, expected)

    def test_request_json_preserves_size_limit_and_closes_response(self):
        response = _JSONResponse(b"1234")
        with self.assertRaises(ProviderResponseTooLarge) as context:
            request_json(
                "request",
                timeout=12,
                max_bytes=3,
                opener=lambda _request, *, timeout: response,
            )
        self.assertEqual(str(context.exception), "provider response exceeds configured size limit")
        self.assertTrue(response.closed)
        self.assertEqual(response.close_count, 1)

    def test_request_json_preserves_replaced_response_handle(self):
        cancel_event = threading.Event()
        replacement = object()

        class Response(_JSONResponse):
            def read(self, _size):
                cancel_event._provider_response = replacement
                return b"{}"

        response = Response(b"unused")
        result = request_json(
            "request",
            timeout=12,
            max_bytes=100,
            cancel_event=cancel_event,
            opener=lambda _request, *, timeout: response,
        )
        self.assertEqual(result.payload, {})
        self.assertIs(cancel_event._provider_response, replacement)
        self.assertTrue(response.closed)

    def test_request_json_preserves_read_cancellation_and_closes_response(self):
        cancel_event = threading.Event()

        class Response(_JSONResponse):
            def read(self, _size):
                cancel_event.set()
                return b"{}"

        response = Response(b"unused")
        with self.assertRaises(ProviderRequestCancelled):
            request_json(
                "request",
                timeout=12,
                max_bytes=100,
                cancel_event=cancel_event,
                opener=lambda _request, *, timeout: response,
            )
        self.assertTrue(response.closed)
        self.assertFalse(hasattr(cancel_event, "_provider_response"))

    def test_open_interruptibly_without_cancellation_is_synchronous(self):
        calls = []
        response = object()

        def opener(request, *, timeout):
            calls.append((request, timeout))
            return response

        self.assertIs(open_interruptibly("request", 12, opener=opener), response)
        self.assertEqual(calls, [("request", 12)])

    def test_open_interruptibly_returns_async_response(self):
        entered = threading.Event()
        release = threading.Event()
        response = object()

        def opener(_request, *, timeout):
            self.assertEqual(timeout, 12)
            entered.set()
            release.wait(1)
            return response

        threading.Thread(target=lambda: (entered.wait(1), release.set()), daemon=True).start()
        self.assertIs(open_interruptibly("request", 12, threading.Event(), opener=opener, poll_seconds=0.01), response)

    def test_open_interruptibly_cancels_header_wait_and_closes_late_response(self):
        entered = threading.Event()
        release = threading.Event()
        cancel_event = threading.Event()
        closed = threading.Event()

        class Response:
            def close(self):
                closed.set()

        response = Response()

        def opener(_request, **_kwargs):
            entered.set()
            release.wait(1)
            return response

        result = []
        thread = threading.Thread(
            target=lambda: self._capture(result, open_interruptibly, "request", 12, cancel_event, opener=opener, poll_seconds=0.01),
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(1))
        cancel_event.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0][0], ProviderRequestCancelled)
        release.set()
        self.assertTrue(closed.wait(1))

    def test_open_interruptibly_preserves_opener_exception(self):
        expected = RuntimeError("opener failed")

        def opener(_request, **_kwargs):
            raise expected

        with self.assertRaises(RuntimeError) as context:
            open_interruptibly("request", 12, threading.Event(), opener=opener, poll_seconds=0.01)
        self.assertIs(context.exception, expected)

    def test_read_response_registers_and_cleans_response_on_success(self):
        started = threading.Event()
        release = threading.Event()
        cancel_event = threading.Event()

        class Response:
            def read(self, _size):
                started.set()
                release.wait(1)
                return b"ok"

        response = Response()
        result = []
        thread = threading.Thread(target=lambda: self._capture(result, read_response, response, 10, cancel_event), daemon=True)
        thread.start()
        self.assertTrue(started.wait(1))
        self.assertIs(cancel_event._provider_response, response)
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [(b"ok", None)])
        self.assertFalse(hasattr(cancel_event, "_provider_response"))

    def test_read_response_cleans_response_on_read_error(self):
        cancel_event = threading.Event()

        class Response:
            def read(self, _size):
                self.assert_registered = getattr(cancel_event, "_provider_response", None)
                raise OSError("read failed")

        response = Response()
        with self.assertRaises(OSError):
            read_response(response, 10, cancel_event)
        self.assertIs(response.assert_registered, response)
        self.assertFalse(hasattr(cancel_event, "_provider_response"))

    def test_read_response_cancels_before_read(self):
        cancel_event = threading.Event()
        cancel_event.set()

        class Response:
            def read(self, _size):
                raise AssertionError("read must not start")

        with self.assertRaises(ProviderRequestCancelled):
            read_response(Response(), 10, cancel_event)

    def test_read_response_cancels_after_read(self):
        cancel_event = threading.Event()

        class Response:
            def read(self, _size):
                cancel_event.set()
                return b"ok"

        with self.assertRaises(ProviderRequestCancelled):
            read_response(Response(), 10, cancel_event)
        self.assertFalse(hasattr(cancel_event, "_provider_response"))

    def test_read_response_preserves_replaced_response_handle(self):
        cancel_event = threading.Event()
        replacement = object()

        class Response:
            def read(self, _size):
                cancel_event._provider_response = replacement
                return b"ok"

        self.assertEqual(read_response(Response(), 10, cancel_event), b"ok")
        self.assertIs(cancel_event._provider_response, replacement)

    def test_read_response_preserves_size_limit_error(self):
        cancel_event = threading.Event()

        class Response:
            def read(self, _size):
                return b"1234"

        with self.assertRaisesRegex(ProviderResponseTooLarge, "provider response exceeds configured size limit"):
            read_response(Response(), 3, cancel_event)
        self.assertFalse(hasattr(cancel_event, "_provider_response"))

    @staticmethod
    def _capture(result, function, *args, **kwargs):
        try:
            result.append((function(*args, **kwargs), None))
        except BaseException as exc:  # noqa: BLE001
            result.append((type(exc), exc))

    def test_request_body_requires_exactly_one_body_source(self):
        self.assertEqual(request_body({"ü": "ja"}, None), b'{"\\u00fc": "ja"}')
        self.assertEqual(request_body(None, b"raw"), b"raw")
        self.assertIsNone(request_body(None, None))
        with self.assertRaises(ValueError):
            request_body({}, b"raw")

    def test_json_request_parts_builds_safe_request_and_context(self):
        request, parsed_url, headers, context = json_request_parts(
            "post",
            "https://example.test/api/v1/resource?id=secret&blank=",
            payload={"name": "synthetic"},
            headers={"X-Test": "yes"},
            timeout=12,
            service="synthetic",
            content_type="application/custom+json",
            app_version="1.2.3",
            operation_context={"operation_id": "op-1", "trigger": "test", "phase": "wire"},
        )
        self.assertEqual(request.data, b'{"name": "synthetic"}')
        self.assertEqual(parsed_url.netloc, "example.test")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["User-Agent"], "IntervalsCoach/1.2.3")
        self.assertEqual(headers["Content-Type"], "application/custom+json")
        self.assertEqual(context["service"], "synthetic")
        self.assertEqual(context["method"], "POST")
        self.assertEqual(context["query_keys"], ["blank", "id"])
        self.assertEqual(context["request_bytes"], len(request.data))
        self.assertEqual(
            {key: context[key] for key in ("operation_id", "trigger", "phase")},
            {"operation_id": "op-1", "trigger": "test", "phase": "wire"},
        )
        self.assertNotIn("secret", context.values())

    def test_json_request_parts_does_not_add_content_type_without_body(self):
        _, _, headers, context = json_request_parts(
            "get",
            "https://example.test/resource",
            content_type="application/custom+json",
            app_version="1.2.3",
        )
        self.assertNotIn("Content-Type", headers)
        self.assertEqual(context["request_bytes"], 0)

    def test_json_request_parts_derives_phase_when_context_omits_it(self):
        _, _, _, context = json_request_parts(
            "post",
            "https://example.test/api/v1/resource",
            raw_body=b"raw",
            app_version="1.2.3",
            operation_context={"operation_id": "op-1", "trigger": "test"},
        )
        self.assertEqual(context["phase"], "resource")

    def test_read_error_body_bounds_and_closes_sized_response(self):
        class Response:
            def __init__(self):
                self.closed = False
                self.read_size = None

            def read(self, size):
                self.read_size = size
                return b"012345"

            def close(self):
                self.closed = True

        response = Response()
        self.assertEqual(read_error_body(response, 3), b"0123")
        self.assertEqual(response.read_size, 4)
        self.assertTrue(response.closed)

    def test_read_error_body_bounds_fakes_without_read_size_and_closes(self):
        class Response:
            def __init__(self):
                self.closed = False

            def read(self):
                return b"012345"

            def close(self):
                self.closed = True

        response = Response()
        self.assertEqual(read_error_body(response, 3), b"0123")
        self.assertTrue(response.closed)

    def test_multipart_form_data_has_deterministic_exact_wire_bytes(self):
        body, content_type = multipart_form_data(
            [("model", "gpt-transcribe"), ("languages[]", "de")],
            "file",
            "voice.webm",
            "audio/webm",
            b"\x00\xffaudio\r\n",
            boundary_token="test-boundary",
        )
        boundary = b"----IntervalsCoachtest-boundary"
        expected = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="model"\r\n\r\n'
            b"gpt-transcribe\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="languages[]"\r\n\r\n'
            b"de\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="voice.webm"\r\n'
            b"Content-Type: audio/webm\r\n\r\n"
            b"\x00\xffaudio\r\n"
            b"\r\n--" + boundary + b"--\r\n"
        )
        self.assertEqual(body, expected)
        self.assertEqual(content_type, "multipart/form-data; boundary=----IntervalsCoachtest-boundary")

    def test_multipart_form_data_default_boundary_has_expected_prefix_and_hex_token(self):
        body, content_type = multipart_form_data([], "file", "voice.mp3", "audio/mpeg", b"audio")
        self.assertRegex(content_type, r"^multipart/form-data; boundary=----IntervalsCoach[0-9a-f]{32}$")
        boundary = content_type.split("=", 1)[1].encode("ascii")
        self.assertTrue(body.startswith(b"--" + boundary + b"\r\n"))
        self.assertTrue(body.endswith(b"\r\n--" + boundary + b"--\r\n"))

    def test_read_bounded_response_rejects_oversized_body(self):
        class Response:
            def read(self, size):
                return b"1234"

        with self.assertRaises(ValueError):
            read_bounded_response(Response(), 3)

    def test_error_detail_is_redacted_and_bounded(self):
        raw = b'{"error":{"message":"authorization: bearer secret-token"}}'
        self.assertEqual(error_detail(raw), "authorization: [REDACTED]")
        self.assertEqual(error_detail(b'{"error":"Invalid workout type"}'), "Invalid workout type")
        self.assertEqual(error_detail(b'{"error":{},"message":"top-level detail"}'), "top-level detail")
        self.assertEqual(error_detail(b'{"error":"","message":"top-level detail"}'), "top-level detail")

    def test_external_call_logs_and_captures_safe_success_metadata_once(self):
        logger = _CallLogger()
        capture = _DiagnosticCapture()
        calls = []
        result = external_call(
            "synthetic",
            "fetch",
            lambda: calls.append(True) or {"secret": "provider payload", "items": [1, 2]},
            {"date": "2026-09-19", "secret": "must not appear"},
            logger=logger,
            diagnostic_capture=capture,
            operation_context={"operation_id": "op-1", "trigger": "manual", "phase": "sync", "ignored": "nope"},
        )

        self.assertEqual(result, {"secret": "provider payload", "items": [1, 2]})
        self.assertEqual(calls, [True])
        self.assertEqual([record[2]["extra"]["event"] for record in logger.records], [
            "external_call_started", "external_call_completed",
        ])
        start_context = logger.records[0][2]["extra"]["context"]
        self.assertEqual(
            {key: start_context[key] for key in ("operation_id", "trigger", "phase")},
            {"operation_id": "op-1", "trigger": "manual", "phase": "fetch"},
        )
        self.assertEqual(start_context["date"], "2026-09-19")
        self.assertNotIn("must not appear", repr(logger.records))
        self.assertNotIn("provider payload", repr(logger.records))
        self.assertEqual([event for event, _details in capture.entries], [
            "external_call_started", "external_call_completed",
        ])
        self.assertEqual(capture.entries[1][1]["response"], {
            "shape": {"type": "object", "field_count": 2, "fields": ["secret", "items"],
                      "sample": {"type": "string", "length": 16}},
        })
        self.assertNotIn("provider payload", repr(capture.entries))

    def test_external_call_reraises_app_error_unchanged_and_captures_failure(self):
        logger = _CallLogger()
        capture = _DiagnosticCapture()
        expected = AppError(409, "synthetic message", reason="already_exists")
        calls = []

        def call():
            calls.append(True)
            raise expected

        with self.assertRaises(AppError) as raised:
            external_call("synthetic", "create", call, logger=logger, diagnostic_capture=capture)

        self.assertIs(raised.exception, expected)
        self.assertEqual(calls, [True])
        self.assertEqual([record[2]["extra"]["event"] for record in logger.records], ["external_call_started"])
        self.assertEqual([event for event, _details in capture.entries], [
            "external_call_started", "external_call_failed",
        ])
        failure = capture.entries[1][1]
        self.assertEqual(failure["error"], {"type": "AppError", "status": 409, "reason": "already_exists"})
        self.assertNotIn("synthetic message", repr(capture.entries))

    def test_external_call_translates_unexpected_exception_with_cause_and_no_leak(self):
        logger = _CallLogger()
        capture = _DiagnosticCapture()
        expected = RuntimeError("provider payload must not leak")
        calls = []

        def call():
            calls.append(True)
            raise expected

        with self.assertRaises(AppError) as raised:
            external_call("synthetic", "fetch", call, logger=logger, diagnostic_capture=capture)

        self.assertEqual(calls, [True])
        self.assertIs(raised.exception.__cause__, expected)
        self.assertEqual(raised.exception.reason, "provider_client_error")
        self.assertEqual(logger.records[1][0], "exception")
        self.assertEqual(logger.records[1][2]["extra"]["context"]["error_code"], "internal_error")
        self.assertNotIn("provider payload must not leak", repr(logger.records[1][2]["extra"]))
        self.assertEqual(capture.entries[1][1]["error"], {"type": "RuntimeError"})
        self.assertNotIn("provider payload must not leak", repr(capture.entries))

    def test_external_call_classifies_timeout_without_exposing_error_text(self):
        logger = _CallLogger()
        capture = _DiagnosticCapture()
        with self.assertRaises(AppError):
            external_call(
                "synthetic",
                "fetch",
                lambda: (_ for _ in ()).throw(TimeoutError("provider timeout details")),
                logger=logger,
                diagnostic_capture=capture,
            )

        self.assertEqual(logger.records[1][2]["extra"]["context"]["error_code"], "timeout")
        self.assertEqual(capture.entries[1][1]["error"], {"type": "TimeoutError"})


if __name__ == "__main__":
    unittest.main()
