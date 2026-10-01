import socket
import threading
from http.server import ThreadingHTTPServer
from typing import Any


class CoachHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    max_active_requests = 32

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._request_slots = threading.BoundedSemaphore(self.max_active_requests)
        super().__init__(*args, **kwargs)

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()
