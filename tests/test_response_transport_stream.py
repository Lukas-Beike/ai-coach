"""File streams end on a stalled client, never on a total time limit."""

from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.http_api import response_transport
from backend.http_api.response_transport import HttpResponseTransport

PAYLOAD_BYTES = 2 * 1024 * 1024
IDLE_TIMEOUT_SECONDS = 0.5


class SocketWriter:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection

    def write(self, data: bytes) -> int:
        self._connection.sendall(data)
        return len(data)


class SocketHandler:
    client_disconnect_errors = (
        BrokenPipeError,
        ConnectionResetError,
        ConnectionAbortedError,
        TimeoutError,
    )

    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.wfile = SocketWriter(connection)
        self.send_response = Mock()
        self.send_header = Mock()
        self.end_headers = Mock()
        self.log_client_disconnect = Mock()
        self.close_connection = False


class FileStreamIdleTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "backup.bin"
        self.path.write_bytes(b"x" * PAYLOAD_BYTES)
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.client = socket.socket()
        self.addCleanup(self.client.close)
        # Small buffers make the sender block as soon as the client stops reading.
        self.client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
        self.client.connect(listener.getsockname())
        server_side, _address = listener.accept()
        self.addCleanup(server_side.close)
        server_side.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
        server_side.settimeout(20)
        self.handler = SocketHandler(server_side)
        patcher = patch.object(
            response_transport, "STREAM_IDLE_TIMEOUT_SECONDS", IDLE_TIMEOUT_SECONDS
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def stream(self) -> threading.Thread:
        thread = threading.Thread(
            target=HttpResponseTransport().send_file_stream,
            args=(self.handler, self.path, "application/octet-stream", "backup.bin"),
        )
        thread.start()
        self.addCleanup(thread.join)
        return thread

    def test_slow_client_that_keeps_reading_receives_the_whole_file(self) -> None:
        thread = self.stream()
        received = 0
        started = time.monotonic()
        while received < PAYLOAD_BYTES:
            chunk = self.client.recv(32 * 1024)
            self.assertTrue(chunk)
            received += len(chunk)
            time.sleep(0.02)
        thread.join(timeout=5)

        self.assertGreater(time.monotonic() - started, IDLE_TIMEOUT_SECONDS * 2)
        self.assertEqual(received, PAYLOAD_BYTES)
        self.handler.log_client_disconnect.assert_not_called()
        self.assertEqual(self.handler.connection.gettimeout(), 20)

    def test_stalled_client_ends_the_stream_after_the_idle_timeout(self) -> None:
        started = time.monotonic()
        thread = self.stream()
        thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 5)
        self.handler.log_client_disconnect.assert_called_once()
        self.assertTrue(self.handler.close_connection)
        self.assertEqual(self.handler.connection.gettimeout(), 20)


if __name__ == "__main__":
    unittest.main()
