import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request

from backend.providers import http, openai


class ProviderRedirectTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body_length = int(self.headers.get("Content-Length", "0"))
                if body_length:
                    self.rfile.read(body_length)
                if self.path.startswith("/redirect/"):
                    _, _, status, host = self.path.split("/")
                    redirect_host = "localhost" if host == "localhost" else "127.0.0.1"
                    self.send_response(int(status))
                    self.send_header(
                        "Location",
                        f"http://{redirect_host}:{self.server.server_port}/destination",
                    )
                    self.end_headers()
                    return
                received.append(dict(self.headers))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            do_POST = do_GET

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method="GET"):
        return Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            data=b"{}" if method == "POST" else None,
            headers={
                "Authorization": "Synthetic provider header",
                "X-Goog-Api-Key": "synthetic-provider-header",
            },
            method=method,
        )

    def test_json_transport_rejects_same_and_cross_origin_redirects(self):
        for status in (301, 302, 303, 307, 308):
            for host in ("127.0.0.1", "localhost"):
                for method in ("GET", "POST"):
                    with self.subTest(status=status, host=host, method=method):
                        with self.assertRaises(HTTPError) as caught:
                            http.request_json(
                                self.request(f"/redirect/{status}/{host}", method),
                                timeout=2,
                                max_bytes=1024,
                            )
                        self.assertEqual(caught.exception.code, status)
                        caught.exception.close()
                        self.assertEqual(self.received, [])

    def test_streaming_openers_reject_redirects(self):
        opener = openai.urlopen
        self.assertIs(opener, http.urlopen)
        with (
            self.assertRaises(HTTPError) as caught,
            http.open_interruptibly(
                self.request("/redirect/302/localhost", "POST"),
                timeout=2,
                cancel_event=threading.Event(),
                opener=opener,
            ),
        ):
            self.fail("A redirected response must not be opened")
        caught.exception.close()
        self.assertEqual(self.received, [])

    def test_direct_request_preserves_headers_and_json(self):
        result = http.request_json(
            self.request("/destination", "POST"), timeout=2, max_bytes=1024
        )
        self.assertEqual(result.payload, {"ok": True})
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0]["Authorization"], "Synthetic provider header")
        self.assertEqual(
            self.received[0]["X-Goog-Api-Key"], "synthetic-provider-header"
        )
