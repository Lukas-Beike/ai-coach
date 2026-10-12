"""Wahoo connection through the real HTTP handler with a temporary database."""

from __future__ import annotations

import http.client
import io
import json
import threading
import zipfile
from dataclasses import replace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from server_test_support import ServerTestCase, create_test_session, server

from backend.http_api import server as http_server_module

REDIRECT = "https://coach.example.invalid/api/wahoo/callback"
ACCESS = "tok-access-SENTINEL"
REFRESH = "tok-refresh-SENTINEL"
SECRET = "client-secret-SENTINEL"
CODE = "auth-code-SENTINEL"


class WahooHttpTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.transport = Mock(
            return_value={
                "access_token": ACCESS,
                "refresh_token": REFRESH,
                "expires_in": 3600,
            }
        )
        patches = (
            patch.object(
                server,
                "CONFIG",
                replace(
                    server.CONFIG,
                    wahoo_client_id="client-id",
                    wahoo_client_secret=SECRET,
                    wahoo_redirect_uri=REDIRECT,
                ),
            ),
            patch.object(
                server.app_config, "security_configuration_error", return_value=None
            ),
            patch.object(
                server.PROVIDER_TRANSPORT,
                "json_http_client",
                return_value=Mock(request=self.transport),
            ),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        server.WAHOO_CONNECTION._service = None
        self.addCleanup(setattr, server.WAHOO_CONNECTION, "_service", None)
        handler_class = server.HTTP_API.request_handler_class()
        handler_class.protocol_version = "HTTP/1.1"
        self.httpd = http_server_module.CoachHTTPServer(("127.0.0.1", 0), handler_class)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.session = create_test_session(server)

    def call(self, method, path, *, session=True, csrf=True):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=10
        )
        headers = {}
        if session:
            headers["Cookie"] = f"ic_session={self.session}"
        if csrf:
            headers["X-CSRF-Token"] = "csrf"
        body = b"{}" if method == "POST" else None
        if body:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def start(self):
        response, data = self.call("POST", "/api/wahoo/connect")
        self.assertEqual(response.status, 200)
        url = json.loads(data)["authorize_url"]
        return parse_qs(urlsplit(url).query)["state"][0]

    def test_post_routes_require_session_and_csrf(self):
        for path in ("/api/wahoo/connect", "/api/wahoo/disconnect"):
            with self.subTest(path=path):
                response, _ = self.call("POST", path, session=False, csrf=False)
                self.assertEqual(response.status, 401)
                response, _ = self.call("POST", path, csrf=False)
                self.assertEqual(response.status, 403)
        self.transport.assert_not_called()

    def test_connect_callback_without_session_and_status_without_tokens(self):
        state = self.start()
        response, _ = self.call(
            "GET",
            f"/api/wahoo/callback?code={CODE}&state={state}",
            session=False,
            csrf=False,
        )
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "/?wahoo=connected")
        self.assertNotIn(CODE, str(response.getheaders()))
        self.assertNotIn(state, str(response.getheaders()))

        response, data = self.call("GET", "/api/bootstrap", csrf=False)
        status = json.loads(data)["wahoo"]
        self.assertTrue(status["connected"])
        self.assertTrue(status["configured"])
        for sentinel in (ACCESS, REFRESH, SECRET, CODE, state):
            self.assertNotIn(sentinel.encode(), data)

        for path in ("/api/privacy/export", "/api/diagnostics"):
            with self.subTest(path=path):
                response, data = self.call("GET", path, csrf=False)
                self.assertEqual(response.status, 200)
                haystack = data
                if zipfile.is_zipfile(io.BytesIO(data)):
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        haystack = b"".join(archive.read(n) for n in archive.namelist())
                for sentinel in (ACCESS, REFRESH, SECRET):
                    self.assertNotIn(sentinel.encode(), haystack)
                self.assertNotIn(b"wahoo_oauth", haystack)

    def test_reused_or_wrong_state_is_redirected_to_error_without_exchange(self):
        state = self.start()
        response, _ = self.call(
            "GET",
            f"/api/wahoo/callback?code={CODE}&state=wrong",
            session=False,
            csrf=False,
        )
        self.assertEqual(response.getheader("Location"), "/?wahoo=error")
        self.transport.assert_not_called()
        self.call(
            "GET",
            f"/api/wahoo/callback?code={CODE}&state={state}",
            session=False,
            csrf=False,
        )
        self.transport.reset_mock()
        response, _ = self.call(
            "GET",
            f"/api/wahoo/callback?code={CODE}&state={state}",
            session=False,
            csrf=False,
        )
        self.assertEqual(response.getheader("Location"), "/?wahoo=error")
        self.transport.assert_not_called()

    def test_disconnect_removes_connection(self):
        state = self.start()
        self.call(
            "GET",
            f"/api/wahoo/callback?code={CODE}&state={state}",
            session=False,
            csrf=False,
        )
        response, data = self.call("POST", "/api/wahoo/disconnect")
        self.assertEqual(response.status, 200)
        self.assertFalse(json.loads(data)["connected"])
        _, data = self.call("GET", "/api/bootstrap", csrf=False)
        self.assertFalse(json.loads(data)["wahoo"]["connected"])

    def test_unconfigured_connect_returns_german_error(self):
        with patch.object(
            server, "CONFIG", replace(server.CONFIG, wahoo_client_secret="")
        ):
            response, data = self.call("POST", "/api/wahoo/connect")
        self.assertEqual(response.status, 503)
        self.assertIn("nicht konfiguriert", data.decode())

    def test_callback_code_and_state_never_reach_logs(self):
        state = self.start()
        with self.assertLogs(server.LOGGER, level="DEBUG") as captured:
            server.LOGGER.info("probe")
            self.call(
                "GET",
                f"/api/wahoo/callback?code={CODE}&state={state}",
                session=False,
                csrf=False,
            )
        joined = "\n".join(captured.output)
        self.assertNotIn(CODE, joined)
        self.assertNotIn(state, joined)
        self.assertNotIn(SECRET, joined)
