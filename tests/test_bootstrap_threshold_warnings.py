"""The bootstrap carries the stale-threshold warning (or null) for the app-wide status strip."""

from __future__ import annotations

import http.client
import json
import threading
from unittest.mock import patch

from server_test_support import ServerTestCase, create_test_session, server

from backend.http_api import server as http_server_module

WARNING = {
    "stale_after_days": 56,
    "sdk_failure": None,
    "items": [
        {
            "label": "FTP Rad",
            "value_text": "250 W",
            "source_label": "Lokal",
            "age_days": 70,
            "reason": "stale",
        }
    ],
}


class BootstrapThresholdWarningTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(
            server.app_config, "security_configuration_error", return_value=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        handler_class = server.HTTP_API.request_handler_class()
        handler_class.protocol_version = "HTTP/1.1"
        self.httpd = http_server_module.CoachHTTPServer(("127.0.0.1", 0), handler_class)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.session = create_test_session(server)

    def bootstrap(self) -> dict:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=10
        )
        connection.request(
            "GET",
            "/api/bootstrap",
            headers={"Cookie": f"ic_session={self.session}"},
        )
        response = connection.getresponse()
        data = response.read()
        connection.close()
        self.assertEqual(response.status, 200)
        return json.loads(data)

    def test_warning_is_in_the_bootstrap_and_null_when_cleared(self):
        with patch.object(server.THRESHOLD_WARNINGS, "read", return_value=WARNING):
            self.assertEqual(self.bootstrap()["threshold_warnings"], WARNING)
        with patch.object(server.THRESHOLD_WARNINGS, "read", return_value=None):
            self.assertIsNone(self.bootstrap()["threshold_warnings"])
