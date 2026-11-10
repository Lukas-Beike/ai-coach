"""Slow and malformed request input over real loopback sockets, synthetic data only."""

from __future__ import annotations

import logging
import socket
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock

from backend.errors import AppError
from backend.http_api.auth import SessionAuthService
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.handler import (
    HttpRequestHandlerDependencies,
    create_request_handler,
)
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.response_transport import HttpResponseTransport

PASSWORD = "synthetic-password-123"
LOGIN_HEADERS = b"POST /api/login HTTP/1.0\r\nContent-Type: application/json\r\n"


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def events(self, name: str) -> list[logging.LogRecord]:
        return [r for r in self.records if getattr(r, "event", None) == name]

    def failures(self) -> list[logging.LogRecord]:
        return [r for r in self.records if r.levelno >= logging.ERROR or r.exc_info]


class UploadRoutes:
    """Stand-in for authenticated body routes: read the body, report its size."""

    def read_and_answer(self, handler, *, json_body=False):
        size = len(handler.read_json() if json_body else handler.read_body())
        handler.send_json(200, {"size": size})


def make_server(*, input_timeout: float, chunk_bytes: int):
    log = logging.getLogger("test.http_input_robustness")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    recorder = RecordingHandler()
    log.addHandler(recorder)
    login_service = SessionAuthService(
        Mock(),
        threading.RLock(),
        cast(Any, SimpleNamespace(app_password=PASSWORD)),
        True,
        RateLimiter(),
    )
    auth_routes = AuthPostRoutes(lambda: login_service, MagicMock())
    routes = UploadRoutes()

    def handle_before_auth(handler, path):
        if path == "/api/upload":
            routes.read_and_answer(handler)
            return True
        return auth_routes.handle(handler, path)

    gate = MagicMock()
    request_auth = Mock()
    dependencies = HttpRequestHandlerDependencies(
        app_version="test",
        logger=log,
        session_auth_service=lambda: request_auth,
        route_dispatcher=SimpleNamespace(
            handle_put=lambda handler, _path: routes.read_and_answer(handler)
        ),
        post_dispatcher=SimpleNamespace(handle_before_auth=handle_before_auth),
        response_transport=HttpResponseTransport(),
        maintenance_gate=gate,
        redact_text=lambda text: text,
        internal_server_error="internal",
        max_body_bytes=256 * 1024,
        max_audio_body_bytes=1024,
        voice_audio_types=(),
        normalize_audio_type=lambda value: value,
        static_asset_service=Mock(),
    )
    base = create_request_handler(dependencies)
    handler_class = type(
        "FastDeadlineHandler",
        (base,),
        {"input_timeout_seconds": input_timeout, "body_chunk_bytes": chunk_bytes},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, recorder


def read_response(connection: socket.socket) -> bytes:
    data = b""
    try:
        while chunk := connection.recv(65536):
            data += chunk
    except ConnectionError:
        pass
    return data


def status_of(response: bytes) -> int | None:
    return int(response.split(b" ", 2)[1]) if response else None


class HttpInputRobustnessTests(unittest.TestCase):
    def start(self, *, input_timeout=0.5, chunk_bytes=4096):
        server, thread, recorder = make_server(
            input_timeout=input_timeout, chunk_bytes=chunk_bytes
        )
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, recorder

    def connect(self, server):
        connection = socket.create_connection(server.server_address, timeout=5)
        self.addCleanup(connection.close)
        return connection

    def request(self, server, head: bytes, body: bytes = b"") -> bytes:
        connection = self.connect(server)
        connection.sendall(head + b"\r\n" + body)
        return read_response(connection)

    def test_steady_trickle_longer_than_one_window_is_accepted(self):
        server, recorder = self.start(input_timeout=0.5, chunk_bytes=4096)
        body = b"x" * 16384
        for method in (b"POST /api/upload", b"PUT /api/anything"):
            with self.subTest(method=method):
                connection = self.connect(server)
                connection.sendall(
                    method
                    + b" HTTP/1.0\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                )
                started = time.monotonic()
                for offset in range(0, len(body), 2048):
                    connection.sendall(body[offset : offset + 2048])
                    time.sleep(0.1)
                elapsed = time.monotonic() - started
                response = read_response(connection)
                # More than the single 0.5 s window the old code allowed.
                self.assertGreater(elapsed, 0.7)
                self.assertEqual(status_of(response), 200)
                self.assertIn(b'"size":16384', response.replace(b" ", b""))
        self.assertEqual(recorder.failures(), [])

    def test_drip_below_the_chunk_rule_closes_without_a_server_error(self):
        server, recorder = self.start(input_timeout=0.4, chunk_bytes=4096)
        for method in (b"POST /api/upload", b"PUT /api/anything"):
            with self.subTest(method=method):
                recorder.records.clear()
                connection = self.connect(server)
                connection.sendall(
                    method + b" HTTP/1.0\r\nContent-Length: 16384\r\n\r\n"
                )
                try:
                    for _ in range(40):
                        connection.sendall(b"x")
                        time.sleep(0.05)
                except OSError:
                    pass
                response = read_response(connection)
                self.assertNotEqual(status_of(response), 500)
                self.assertEqual(response, b"")
                deadline = time.monotonic() + 3
                while not recorder.events("http_client_timeout"):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                (record,) = recorder.events("http_client_timeout")
                self.assertEqual(record.levelno, logging.INFO)
                self.assertEqual(
                    record.context["method"], method.split(b" ")[0].decode()
                )
                self.assertEqual(recorder.failures(), [])

    def test_malformed_login_bodies_return_400_without_tracebacks(self):
        server, recorder = self.start()
        bodies = (
            b'{"password": ' + b"1" * 5000 + b"}",
            b"[" * 100_000,
            b'{"password": "\xff\xfe"}',
            b'{"password": ',
            b"[]",
        )
        for body in bodies:
            head = LOGIN_HEADERS + f"Content-Length: {len(body)}\r\n".encode()
            response = self.request(server, head, body)
            self.assertEqual(status_of(response), 400, body[:20])
            if body != b"[]":
                self.assertIn("Ungültiges JSON.".encode(), response)
        self.assertEqual(recorder.failures(), [])

    def test_oversized_numbers_still_count_against_the_login_limiter(self):
        server, recorder = self.start()
        body = b'{"password": ' + b"1" * 5000 + b"}"
        head = LOGIN_HEADERS + f"Content-Length: {len(body)}\r\n".encode()
        statuses = [status_of(self.request(server, head, body)) for _ in range(6)]
        self.assertEqual(statuses, [400] * 5 + [429])
        self.assertEqual(recorder.failures(), [])

    def test_oversize_body_limit_is_unchanged(self):
        server, recorder = self.start()
        head = (
            b"POST /api/upload HTTP/1.0\r\nContent-Length: "
            + str(256 * 1024 + 1).encode()
            + b"\r\n"
        )
        self.assertEqual(status_of(self.request(server, head)), 413)
        self.assertEqual(recorder.failures(), [])


class ChatHistoryCursorTests(unittest.TestCase):
    def page(self, cursor):
        history = Mock()
        history.page.return_value = ("generation", [])
        service = ChatHistoryPageService(history, Mock(current=Mock(return_value=[])))
        service.page(cursor=cursor, limit=10)
        return history

    @staticmethod
    def cursor(value):
        from backend.http_api.pagination import encode_page_cursor

        return encode_page_cursor(value)

    def test_ids_in_the_sqlite_range_are_used(self):
        for value, expected in (
            (42, 42),
            ("42", 42),
            (2**63 - 1, 2**63 - 1),
            ("9" * 18, 10**18 - 1),
        ):
            with self.subTest(value=value):
                history = self.page(self.cursor(value))
                self.assertEqual(
                    history.page.call_args.kwargs["before_message_id"], expected
                )

    def test_no_cursor_reads_the_newest_page(self):
        history = self.page(None)
        self.assertIsNone(history.page.call_args.kwargs["before_message_id"])

    def test_out_of_range_or_malformed_cursors_are_a_400(self):
        for cursor in (
            self.cursor(2**70),
            self.cursor(-1),
            self.cursor("9" * 20),
            self.cursor("1" * 5000),
            self.cursor(True),
            self.cursor(["x"]),
            "not-a-cursor",
            "A" * 600,
        ):
            with self.subTest(cursor=cursor[:20]):
                with self.assertRaises(AppError) as raised:
                    self.page(cursor)
                self.assertEqual(
                    (raised.exception.status, raised.exception.reason),
                    (400, "invalid_page_cursor"),
                )


if __name__ == "__main__":
    unittest.main()
