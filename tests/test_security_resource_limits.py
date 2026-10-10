"""Availability regressions using isolated sockets and synthetic inputs only."""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.http_api.auth import SessionAuthService
from backend.http_api.handler import RequestHandler
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.server import CoachHTTPServer
from backend.providers import calendar as calendar_provider
from backend.runtime.socket_deadline import SocketDeadline


class CalendarResourceLimitsTests(unittest.TestCase):
    def test_rdate_deduplication_is_linear(self):
        class CountedDateTime(datetime):
            comparisons = 0
            __hash__ = datetime.__hash__

            def __eq__(self, other):
                CountedDateTime.comparisons += 1
                return super().__eq__(other)

        start = CountedDateTime(2026, 9, 1, tzinfo=timezone.utc)
        values = [start + timedelta(minutes=i) for i in range(800)]
        event = {"uid": "synthetic", "start": start, "rdates": values + values}
        records = list(
            calendar_provider._ical_instances(
                event, date(2026, 9, 1), date(2026, 9, 2), timezone.utc
            )
        )
        self.assertEqual(len(records), 800)
        self.assertLessEqual(CountedDateTime.comparisons, len(values) * 4)

    def test_folded_and_repeated_rdates_bound_record_construction(self):
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        values = [
            (start + timedelta(minutes=i)).strftime("%Y%m%dT%H%M%SZ")
            for i in range(1002)
        ]
        for properties in (
            "RDATE:" + ",\r\n ".join(values),
            "\r\n".join("RDATE:" + value for value in values),
        ):
            payload = (
                "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:synthetic\r\n"
                "DTSTART:20260901T000000Z\r\n"
                + properties
                + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            ).encode()
            with (
                self.subTest(form=properties[:30]),
                patch.object(
                    calendar_provider.uuid, "uuid5", wraps=calendar_provider.uuid.uuid5
                ) as identifiers,
                self.assertRaises(AppError) as caught,
            ):
                calendar_provider.parse_ical_calendar(
                    payload, local_zone=timezone.utc, today=start.date()
                )
            self.assertEqual(caught.exception.status, 400)
            self.assertLessEqual(identifiers.call_count, 1001)

    def test_rdate_limit_counts_only_unique_surviving_window_instances(self):
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        excluded = [start + timedelta(minutes=i) for i in range(1500)]
        kept = start + timedelta(days=2)
        event = {
            "uid": "synthetic",
            "start": start,
            "rdates": excluded + [kept] * 1500 + [start - timedelta(days=10)],
            "exdates": excluded[:-1],
        }
        records = list(
            calendar_provider._ical_instances(
                event, start.date(), kept.date(), timezone.utc, {excluded[-1]}
            )
        )
        self.assertEqual([item["start_local"] for item in records], [kept.isoformat()])

    def test_duplicate_components_preserve_global_capacity_and_first_wins(self):
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        values = [
            (start + timedelta(minutes=i)).strftime("%Y%m%dT%H%M%SZ")
            for i in range(1000)
        ]
        component = (
            "BEGIN:VEVENT\r\nUID:synthetic\r\nDTSTART:20260901T000000Z\r\n"
            "SUMMARY:first\r\nRDATE:" + ",\r\n ".join(values) + "\r\nEND:VEVENT\r\n"
        )
        payload = (
            "BEGIN:VCALENDAR\r\n"
            + component
            + component.replace("SUMMARY:first", "SUMMARY:second")
            + "END:VCALENDAR\r\n"
        ).encode()
        records = calendar_provider.parse_ical_calendar(
            payload, local_zone=timezone.utc, today=start.date()
        )
        self.assertEqual(len(records), 1000)
        self.assertEqual({item["name"] for item in records}, {"first"})

    def test_historical_master_matching_is_linear(self):
        class CountedEvent(dict):
            uid_reads = 0

            def get(self, key, default=None):
                if key == "uid":
                    CountedEvent.uid_reads += 1
                return super().get(key, default)

            def __getitem__(self, key):
                if key == "uid":
                    CountedEvent.uid_reads += 1
                return super().__getitem__(key)

        events = [CountedEvent(uid=str(i)) for i in range(200)]
        with patch.object(calendar_provider, "_ical_add_result_instances") as expand:
            calendar_provider._ical_add_master_results(
                {}, events, date(2026, 9, 1), date(2026, 9, 2), timezone.utc
            )
        self.assertEqual(expand.call_count, 200)
        self.assertLessEqual(CountedEvent.uid_reads, 600)

    def test_raw_component_limit_includes_out_of_window_and_cancelled_exceptions(self):
        for event in (
            "UID:old\r\nDTSTART:20000101T000000Z",
            "UID:old\r\nRECURRENCE-ID:20000101T000000Z\r\nSTATUS:CANCELLED",
        ):
            payload = (
                "BEGIN:VCALENDAR\r\n"
                + ("BEGIN:VEVENT\r\n" + event + "\r\nEND:VEVENT\r\n") * 3
                + "END:VCALENDAR\r\n"
            ).encode()
            with (
                self.subTest(event=event),
                patch.object(calendar_provider, "ICAL_MAX_RAW_EVENTS", 2),
                self.assertRaises(AppError) as caught,
            ):
                calendar_provider.parse_ical_calendar(
                    payload, local_zone=timezone.utc, today=date(2026, 9, 1)
                )
            self.assertEqual(caught.exception.status, 400)

    def test_many_folds_preserve_exact_text_and_physical_line_limit(self):
        for newline in ("\r\n", "\n", "\r"):
            text = newline.join(["DESCRIPTION:start", *([" x", "\ty"] * 20000)])
            self.assertEqual(
                calendar_provider._unfold_lines(text),
                ["DESCRIPTION:start" + "xy" * 20000],
            )
        self.assertEqual(calendar_provider._unfold_lines(" orphan\n x"), [" orphanx"])
        with self.assertRaises(AppError):
            calendar_provider._unfold_lines("x" * 20001)

    def test_unfolding_does_not_repeatedly_copy_accumulated_lines(self):
        class CountedText(str):
            copied = 0

            def replace(self, *args):
                return CountedText(super().replace(*args))

            def split(self, *args):
                return [CountedText(line) for line in super().split(*args)]

            def __getitem__(self, key):
                return CountedText(super().__getitem__(key))

            def __add__(self, other):
                CountedText.copied += len(self) + len(other)
                return CountedText(super().__add__(other))

        text = CountedText("DESCRIPTION:start\n" + " x\n" * 2000)
        self.assertEqual(
            calendar_provider._unfold_lines(text)[0], "DESCRIPTION:start" + "x" * 2000
        )
        self.assertLessEqual(CountedText.copied, len(text) * 2)

    def test_calendar_deadline_interrupts_progressing_headers_body_and_chunk_framing(
        self,
    ):
        for prefix in (
            b"HTTP/1.1 200 OK\r\nX-Test: ",
            b"HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1;extension=",
        ):
            with self.subTest(prefix=prefix):
                self._calendar_transfer(prefix, drip=True)

    def test_regular_calendar_transfer_and_timer_cleanup(self):
        self._calendar_transfer(
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata", drip=False
        )

    def _calendar_transfer(self, prefix, *, drip):
        reader, writer = socket.socketpair()
        stopped = threading.Event()

        def send():
            try:
                writer.recv(1024)
                writer.sendall(prefix)
                if drip:
                    for _ in range(100):
                        if stopped.wait(0.01):
                            break
                        writer.sendall(b"x")
            except OSError:
                pass
            finally:
                writer.close()

        producer = threading.Thread(target=send)
        producer.start()
        context = Mock()
        context.wrap_socket.return_value = reader
        deadline = time.perf_counter() + (0.2 if drip else 2)
        try:
            with patch.object(
                calendar_provider.socket, "create_connection", return_value=reader
            ):
                if drip:
                    started = time.monotonic()
                    with self.assertRaises(TimeoutError):
                        calendar_provider._fetch_calendar_address(
                            ipaddress.ip_address("93.184.216.34"),
                            443,
                            "calendar.invalid",
                            context,
                            b"GET / HTTP/1.1\r\n\r\n",
                            deadline,
                        )
                    self.assertLess(time.monotonic() - started, 1)
                else:
                    payload, status = calendar_provider._fetch_calendar_address(
                        ipaddress.ip_address("93.184.216.34"),
                        443,
                        "calendar.invalid",
                        context,
                        b"GET / HTTP/1.1\r\n\r\n",
                        deadline,
                    )
                    self.assertEqual((payload, status), (b"data", 200))
            self.assertEqual(reader.fileno(), -1)
        finally:
            stopped.set()
            producer.join(2)
            reader.close()
            self.assertFalse(producer.is_alive())


class HttpResourceLimitsTests(unittest.TestCase):
    def test_login_throttles_before_reading_and_counts_malformed_requests(self):
        config = SimpleNamespace(app_password="synthetic-password-123")
        auth = SessionAuthService(
            Mock(), threading.RLock(), config, True, RateLimiter()
        )
        handler = Mock(client_address=("127.0.0.1", 1))
        handler.read_json.side_effect = AppError(400, "synthetic malformed JSON")
        for _ in range(5):
            with self.assertRaises(AppError) as caught:
                auth.login_user(handler)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(AppError) as caught:
            auth.login_user(handler)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(handler.read_json.call_count, 5)

    def test_login_normal_body_is_admitted_once_and_wrong_password_stays_401(self):
        limiter = Mock()
        limiter.allow.return_value = (True, 0)
        auth = SessionAuthService(
            Mock(),
            threading.RLock(),
            SimpleNamespace(app_password="synthetic-password-123"),
            True,
            limiter,
        )
        handler = Mock(client_address=("127.0.0.1", 1))
        handler.read_json.return_value = {"password": "wrong"}
        with self.assertRaises(AppError) as caught:
            auth.login_user(handler)
        self.assertEqual(caught.exception.status, 401)
        limiter.allow.assert_called_once_with("login:127.0.0.1", 5, 900)
        handler.read_json.assert_called_once_with()

    def test_handler_slots_recover_when_thread_start_fails(self):
        class OneSlotServer(CoachHTTPServer):
            max_active_requests = 1

        with OneSlotServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
            with (
                patch.object(
                    ThreadingHTTPServer,
                    "process_request",
                    side_effect=RuntimeError("synthetic"),
                ),
                self.assertRaises(RuntimeError),
            ):
                server.process_request(Mock(), ("127.0.0.1", 1))
            self.assertTrue(server._request_slots.acquire(blocking=False))
            server._request_slots.release()

    def test_saturated_handler_budget_rejects_and_recovers(self):
        entered = threading.Event()
        release = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                release.wait(2)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        class OneSlotServer(CoachHTTPServer):
            max_active_requests = 1

        with OneSlotServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.01}
            )
            worker.start()
            try:
                with socket.create_connection(
                    server.server_address, timeout=2
                ) as first:
                    first.sendall(b"GET / HTTP/1.0\r\n\r\n")
                    self.assertTrue(entered.wait(1))
                    with socket.create_connection(
                        server.server_address, timeout=2
                    ) as rejected:
                        self.assertEqual(rejected.recv(1), b"")
                    release.set()
                    self.assertIn(b"200", first.recv(1024))
                self.assertTrue(server._request_slots.acquire(timeout=1))
                server._request_slots.release()
                with socket.create_connection(
                    server.server_address, timeout=2
                ) as recovered:
                    recovered.sendall(b"GET / HTTP/1.0\r\n\r\n")
                    self.assertIn(b"200", recovered.recv(1024))
            finally:
                release.set()
                server.shutdown()
                worker.join(2)

    def test_input_deadlines_interrupt_drips_but_do_not_limit_response_duration(self):
        completed = threading.Event()

        class Handler(RequestHandler):
            input_timeout_seconds = 0.2
            dependencies = SimpleNamespace(max_body_bytes=1024, logger=logging.getLogger("test.resource_limits"))

            def do_POST(self):
                try:
                    self.read_json()
                    time.sleep(0.3)
                    self.send_response(200)
                    self.end_headers()
                except TimeoutError, AppError:
                    self.close_connection = True
                finally:
                    completed.set()

            def log_message(self, *args):
                pass

        for initial, suffix in (
            (b"POST / HTTP/1.0\r\nX-Test: ", b"x"),
            (
                b"POST / HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n",
                b" ",
            ),
            (
                b"POST / HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
                None,
            ),
        ):
            with self.subTest(suffix=suffix):
                reader, writer = socket.socketpair()
                writer.settimeout(2)
                worker = threading.Thread(
                    target=Handler, args=(reader, ("127.0.0.1", 1), Mock())
                )
                worker.start()
                try:
                    writer.sendall(initial)
                    if suffix:
                        for _ in range(50):
                            time.sleep(0.01)
                            try:
                                writer.sendall(suffix)
                            except OSError:
                                break
                        try:
                            data = writer.recv(1024)
                        except ConnectionError:
                            data = b""
                        self.assertEqual(data, b"")
                    else:
                        self.assertIn(b"200", writer.recv(1024))
                    worker.join(1)
                    self.assertFalse(worker.is_alive())
                finally:
                    writer.close()
                    reader.close()
                    worker.join(2)

    def test_cancelled_deadline_cannot_interrupt_later_socket_use(self):
        reader, writer = socket.socketpair()
        try:
            with SocketDeadline(reader, 0.05) as deadline:
                deadline.cancel()
                time.sleep(0.08)
                writer.sendall(b"ok")
                self.assertEqual(reader.recv(2), b"ok")
        finally:
            reader.close()
            writer.close()


if __name__ == "__main__":
    unittest.main()
