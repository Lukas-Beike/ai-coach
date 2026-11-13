"""Post-release base scripts against a local fake app; no real server or network."""

import io
import json
import secrets
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prod_client
import prod_diagnostics
import prod_guards
import prod_logs

# The fake app password, generated per run so no fixed credential-like literal exists.
FAKE_LOGIN = secrets.token_hex(12)
RECENT = (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def report(messages=40):
    return {
        "app": {"version": "2.1.2"},
        "sync": {
            "last_error": "provider said: secret detail",
            "providers": {
                "garmin": {"last_sync_at": RECENT, "last_plan_sync_at": None},
                "wahoo": {"last_sync_at": None, "last_plan_sync_at": None},
                "intervals": {"last_sync_at": None, "last_plan_sync_at": RECENT},
            },
        },
        "database": {
            "schema_version": 27,
            "messages": messages,
            "competitions": 3,
            "workout_library_state": {"pending": 1, "note": "text never printed"},
        },
        "plan_sync": {
            "unsynced_total": 2,
            "unsynced_units": [{"has_error": True}, {"has_error": False}],
            "recent_jobs": [
                {
                    "status": "failed",
                    "error_class": "HTTPError",
                    "created_at": RECENT,
                    "items": [{"status": "failed", "error_class": "HTTPError"}],
                }
            ],
        },
        "runtime": {"process_memory": {"rss_bytes": 1000}},
    }


class FakeApp(BaseHTTPRequestHandler):
    state: ClassVar[dict] = {}

    def log_message(self, *_args):
        pass

    def send(self, code, body=None, cookies=()):
        self.send_response(code)
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def session(self):
        return "ic_session=s1" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path == "/api/health":
            return self.send(200, {"status": "ok"})
        if not self.session():
            return self.send(401, {"error": "Anmeldung erforderlich."})
        if self.path == "/api/diagnostics":
            return self.send(200, report(self.state.get("messages", 40)))
        if self.path.startswith("/api/logs"):
            entries = [
                {"level": "ERROR", "event": "plan_push_failed", "message": FAKE_LOGIN},
                {
                    "level": "INFO",
                    "event": "garmin_past_workouts_removed",
                    "context": {"count": 3},
                },
            ]
            return self.send(200, {"entries": entries})
        return self.send(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/login":
            if body.get("password") != FAKE_LOGIN:
                return self.send(401)
            self.state["logins"] = self.state.get("logins", 0) + 1
            return self.send(
                200, {"csrf": "c1"}, ("ic_session=s1; Path=/", "ic_csrf=c1; Path=/")
            )
        if self.path == "/api/logout":
            if not self.session():
                return self.send(401)
            if self.headers.get("X-CSRF-Token") != "c1" and not self.state.get(
                "no_csrf"
            ):
                return self.send(403)
            self.state["logouts"] = self.state.get("logouts", 0) + 1
            return self.send(200, {"status": "ok"})
        return self.send(404)


class ProdChecksTests(unittest.TestCase):
    def setUp(self):
        FakeApp.state = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApp)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secret = Path(self.tmp.name) / "secret"
        self.secret.write_text(FAKE_LOGIN + "\n", encoding="utf-8")

    def run_main(self, module, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = module.main(list(args))
        text = out.getvalue()
        self.assertNotIn(FAKE_LOGIN, text)
        self.assertNotIn("secret detail", text)
        self.assertNotIn("text never printed", text)
        return code, text

    def test_diagnostics_prints_named_fields_and_logs_out(self):
        result = Path(self.tmp.name) / "first.json"
        code, text = self.run_main(
            prod_diagnostics, "--url", self.url, "--password-file", str(self.secret),
            "--expect-version", "2.1.2", "--expect-schema", "27", "--out", str(result),
        )  # fmt: skip
        self.assertEqual(code, 1)  # sync.last_error is set
        self.assertIn("ok version 2.1.2", text)
        self.assertIn("ok schema 27", text)
        self.assertIn("FAIL sync last_error set: True", text)
        self.assertIn("ok provider garmin last sync", text)
        self.assertIn("info provider wahoo last sync never", text)
        self.assertIn("2 unsynced, 1 with error; error kinds: HTTPError 2", text)
        self.assertIn("info workout library: pending 1", text)
        self.assertIn("ok logout 200", text)
        self.assertEqual(FakeApp.state["logouts"], 1)
        self.assertEqual(json.loads(result.read_text())["counts"]["messages"], 40)

        FakeApp.state["messages"] = 39
        code, text = self.run_main(
            prod_diagnostics, "--url", self.url, "--password-file", str(self.secret),
            "--compare", str(result),
        )  # fmt: skip
        self.assertIn("FAIL count messages 40 -> 39", text)
        self.assertIn("ok count competitions 3 -> 3", text)

    def test_diagnostics_version_mismatch_and_wrong_password(self):
        code, text = self.run_main(
            prod_diagnostics, "--url", self.url, "--password-file", str(self.secret),
            "--expect-version", "9.9.9",
        )  # fmt: skip
        self.assertIn("FAIL version 2.1.2 (expected 9.9.9)", text)
        self.secret.write_text("wrong password value", encoding="utf-8")
        code, text = self.run_main(
            prod_diagnostics, "--url", self.url, "--password-file", str(self.secret)
        )
        self.assertEqual(code, 2)
        self.assertIn("FAIL login answered 401", text)
        self.assertNotIn("wrong password value", text)

    def test_result_files_stay_outside_the_repository(self):
        inside = Path(prod_client.ROOT) / "result.json"
        code, text = self.run_main(
            prod_diagnostics, "--url", self.url, "--password-file", str(self.secret),
            "--out", str(inside),
        )  # fmt: skip
        self.assertEqual(code, 2)
        self.assertIn("system temp directory", text)
        self.assertFalse(inside.exists())
        # The password file may come from the T3 secret folder, read only;
        # outputs stay in the temp directory and nothing reads the repository.
        t3 = Path.home() / "t3-folder-for-a-test" / "secrets"
        with mock.patch.object(prod_client, "T3_SECRETS", t3):
            secret = t3 / "app-password"
            self.assertEqual(prod_client.secret_path(str(secret)), secret.resolve())
            for path in (
                prod_client.ROOT / ".env",
                t3.parent / "other",
                "app-password",
            ):
                with self.subTest(path=path), self.assertRaises(prod_client.ProdError):
                    prod_client.secret_path(str(path))
            with self.assertRaisesRegex(prod_client.ProdError, "system temp directory"):
                prod_client.scratch_path(str(t3 / "result.json"))
        # The repository stays excluded even inside an allowed folder.
        with (
            mock.patch.object(prod_client, "T3_SECRETS", prod_client.ROOT.parent),
            self.assertRaises(prod_client.ProdError),
        ):
            prod_client.secret_path(str(prod_client.ROOT / ".env"))

    def test_guards_hold_and_detect_a_missing_csrf_check(self):
        code, text = self.run_main(
            prod_guards, "--url", self.url, "--password-file", str(self.secret)
        )
        self.assertEqual(code, 0, text)
        self.assertIn("ok no session -> 401", text)
        self.assertIn("ok no CSRF token -> 403", text)
        FakeApp.state["no_csrf"] = True
        code, text = self.run_main(
            prod_guards, "--url", self.url, "--password-file", str(self.secret)
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL no CSRF token -> 200", text)

    def test_logs_from_the_app_and_from_a_saved_file(self):
        code, text = self.run_main(
            prod_logs, "--url", self.url, "--password-file", str(self.secret)
        )
        self.assertEqual(code, 1)
        self.assertIn("  ERROR plan_push_failed 1", text)
        self.assertIn("garmin past workouts removed: 3", text)
        self.assertIn("plan sync error events: 1", text)
        log = Path(self.tmp.name) / "container.log"
        log.write_text(
            '2026-11-11T10:00:00Z {"timestamp":"2026-11-11T10:00:00","level":"WARNING",'
            '"event":"weather_refresh_failed","message":"token=abc"}\n'
            "plain line with ERROR and a payload\n"
            '{"timestamp":"2026-11-10T00:00:00","level":"ERROR","event":"old"}\n'
            '{"level":"ERROR","event":"Bad Event; drop table"}\n',
            encoding="utf-8",
        )
        code, text = self.run_main(
            prod_logs, "--log-file", str(log), "--since", "2026-11-11"
        )
        self.assertIn("  WARNING weather_refresh_failed 1", text)
        self.assertIn("  ERROR unparsed 1", text)
        self.assertIn("  ERROR unnamed 1", text)
        self.assertNotIn("old", text)
        self.assertNotIn("token=abc", text)
        self.assertNotIn("payload", text)
        code, text = self.run_main(
            prod_logs, "--log-file", str(Path(prod_client.ROOT) / "README.md")
        )
        self.assertEqual(code, 2)
        self.assertIn("system temp directory", text)


if __name__ == "__main__":
    unittest.main()
