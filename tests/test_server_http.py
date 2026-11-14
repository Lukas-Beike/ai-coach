"""Server integration tests for http."""

import ast
import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import timedelta
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock, call, patch
from urllib.parse import urlencode

import snapshot_seed
from server_test_support import (
    ServerTestCase,
    _transcribe_via_http_route,
    create_test_session,
    server,
)
from support import dispatch_route, store_garmin_activities

from backend.coach import streams as coach_streams
from backend.errors import AppError, public_error_contract
from backend.http_api import auth as http_auth
from backend.http_api import response_transport, responses
from backend.http_api import server as http_server_module
from backend.http_api.handler import create_request_handler
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.readiness import ReadinessService
from backend.http_api.route_table import PUBLIC_API_ROUTES, Access, RouteTable
from backend.providers import http as provider_http
from backend.providers import openai_requests, openai_stream
from backend.providers import weather as weather_provider
from backend.providers.model_seam import ModelRequest
from backend.providers.openai_responses_adapter import request_payload
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

# Matches every id pattern of the routes: [^/]+ and the hex job ids.
SAMPLE_ID = "abc-123"


def _api_route_paths() -> set[str]:
    """Every API path the route owners name, with a sample id for path patterns."""
    paths = {path for path, _provider in DEFAULT_PROVIDER_REGISTRY.full_resync_routes()}
    for module in (Path(server.__file__).parent / "backend" / "http_api").glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            value = (
                str(node.value).strip("^$") if isinstance(node, ast.Constant) else ""
            )
            if value.startswith("/api/"):
                paths.add(re.sub(r"\(.*?\)|\{.*?\}", SAMPLE_ID, value).rstrip("/"))
    paths.discard("/api")
    return paths | {f"{path}/{SAMPLE_ID}" for path in paths}


def _request_status(method, path, headers, port):
    """Status of one request; a socket aborted before the reply is sent once more.

    Under full-suite load on Windows the socket was aborted (WinError 10053)
    before the status line arrived (#2734). A second attempt keeps every
    assertion: a handler that ran is still recorded by the caller.
    """
    try:
        return _send_once(method, path, headers, port)
    except ConnectionAbortedError, ConnectionResetError:
        return _send_once(method, path, headers, port)


def _send_once(method, path, headers, port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        body = None if method == "GET" else b"{}"
        connection.request(method, path, body=body, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


class ServerHttpTests(ServerTestCase):
    def test_every_api_route_rejects_a_request_without_session(self):
        auth = http_auth.SessionAuthService(
            Mock(),
            replace(server.CONFIG_HOLDER.value, app_password="synthetic-password-123"),
            True,
            RateLimiter(),
        )
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.HTTP_API.request_handler_class()
        )
        self.addCleanup(httpd.server_close)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        paths = _api_route_paths()
        self.assertIn("/api/bootstrap", paths)
        statuses = {}
        with patch.object(server, "get_session_auth_service", return_value=auth):
            for method in ("GET", "POST", "PUT"):
                for path in sorted(paths):
                    if (method, path) in PUBLIC_API_ROUTES:
                        continue
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", httpd.server_address[1], timeout=10
                    )
                    # No body: the server rejects before reading one, and an unread
                    # body can make Windows abort the connection.
                    connection.request(method, path)
                    statuses[method, path] = connection.getresponse().status
                    connection.close()
        self.assertEqual(401, statuses["GET", "/api/bootstrap"])
        self.assertEqual(401, statuses["GET", f"/api/activities/{SAMPLE_ID}"])
        self.assertEqual(
            [],
            [
                f"{route}: {status}"
                for route, status in statuses.items()
                if status not in {401, 404}
            ],
            "API routes answered without a session",
        )

    def test_every_table_route_checks_access_before_its_handler_runs(self):
        # Every handler is replaced by one that fails when called, so a 401 or
        # 403 proves the access check ran before any route code or service.
        called = []

        def refuse(handler, request):
            called.append(request.path)
            raise AssertionError("route handler ran before its access check")

        table = server.HTTP_API.route_table
        self.assertEqual(
            {(r.method, r.path) for r in table.routes if r.access is Access.PUBLIC},
            PUBLIC_API_ROUTES,
        )
        dependencies = replace(
            server.HTTP_API.request_handler_class().dependencies,
            route_table=RouteTable(replace(r, handle=refuse) for r in table.routes),
        )

        def serve(dependencies):
            httpd = ThreadingHTTPServer(
                ("127.0.0.1", 0), create_request_handler(dependencies)
            )
            self.addCleanup(httpd.server_close)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.shutdown)
            return httpd.server_address[1]

        port = serve(dependencies)
        # A restore in progress: the maintenance gate refuses every operation.
        restoring = runtime_maintenance.MaintenanceGate()
        restoring.restoring = True
        maintenance_port = serve(replace(dependencies, maintenance_gate=restoring))
        config = replace(
            server.CONFIG_HOLDER.value, app_password="synthetic-password-123"
        )
        without_session = http_auth.SessionAuthService(
            Mock(), config, True, RateLimiter()
        )
        with_session = http_auth.SessionAuthService(
            server.database_manager(), config, True, RateLimiter()
        )
        cookie = {"Cookie": f"{http_auth.SESSION_COOKIE}={create_test_session(server)}"}

        def statuses(auth, access, headers, port=port):
            found = {}
            with patch.object(server, "get_session_auth_service", return_value=auth):
                for route in table.routes:
                    if access is not None and route.access is not access:
                        continue
                    path = re.sub(r"\{.*?\}", "abc-123", route.path)
                    found[route.method, path] = _request_status(
                        route.method, path, headers, port
                    )
            return found

        anonymous = {
            **statuses(without_session, Access.SESSION, {}),
            **statuses(without_session, Access.SESSION_CSRF, {}),
        }
        missing_csrf = statuses(with_session, Access.SESSION_CSRF, cookie)
        self.assertGreater(len(missing_csrf), 40)
        self.assertEqual({401}, set(anonymous.values()), anonymous)
        self.assertEqual({403}, set(missing_csrf.values()), missing_csrf)
        self.assertEqual([], called)
        # During a restore every PUT and every gated POST answers 503 before its
        # handler; GET routes and the ungated POST routes still reach theirs.
        during_restore = statuses(
            http_auth.SessionAuthService(
                server.database_manager(), config, True, RateLimiter()
            ),
            None,
            {**cookie, "X-CSRF-Token": "csrf"},
            maintenance_port,
        )
        refused = {
            (r.method, re.sub(r"\{.*?\}", "abc-123", r.path))
            for r in table.routes
            if r.method == "PUT"
            or (r.method == "POST" and r.gated and r.access is not Access.PUBLIC)
        }
        # Without a session the gate still answers first for PUT, while a POST
        # is refused by its access check before it reaches the gate.
        anonymous_restore = statuses(
            without_session, Access.SESSION_CSRF, {}, maintenance_port
        )
        self.assertEqual(
            {key: 503 if key[0] == "PUT" else 401 for key in anonymous_restore},
            anonymous_restore,
        )
        self.assertEqual(
            {key: 503 for key in refused},
            {key: status for key, status in during_restore.items() if key in refused},
        )
        self.assertEqual(
            sorted(
                path for method, path in during_restore if (method, path) not in refused
            ),
            sorted(called),
        )

    def test_post_checks_session_then_csrf_then_maintenance(self):
        # A restore is in progress, so the gate refuses every gated POST. The
        # access checks still answer first: no session is 401, a session without
        # the CSRF token is 403, and only a complete request reaches the gate.
        called = []

        def refuse(handler, request):
            called.append(request.path)
            raise AssertionError("route handler ran during the maintenance gate")

        route = replace(
            next(
                r
                for r in server.HTTP_API.route_table.routes
                if (r.method, r.path) == ("POST", "/api/weather/sync")
            ),
            handle=refuse,
        )
        self.assertTrue(route.gated)
        restoring = runtime_maintenance.MaintenanceGate()
        restoring.restoring = True
        dependencies = replace(
            server.HTTP_API.request_handler_class().dependencies,
            route_table=RouteTable([route]),
            maintenance_gate=restoring,
        )
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), create_request_handler(dependencies)
        )
        self.addCleanup(httpd.server_close)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        auth = http_auth.SessionAuthService(
            server.database_manager(),
            replace(server.CONFIG_HOLDER.value, app_password="synthetic-password-123"),
            True,
            RateLimiter(),
        )
        cookie = {"Cookie": f"{http_auth.SESSION_COOKIE}={create_test_session(server)}"}

        def post(headers):
            connection = http.client.HTTPConnection(
                "127.0.0.1", httpd.server_address[1], timeout=10
            )
            connection.request("POST", "/api/weather/sync", body=b"{}", headers=headers)
            status = connection.getresponse().status
            connection.close()
            return status

        with patch.object(server, "get_session_auth_service", return_value=auth):
            self.assertEqual(401, post({}))
            self.assertEqual(403, post(cookie))
            self.assertEqual(503, post({**cookie, "X-CSRF-Token": "csrf"}))
        self.assertEqual([], called)

    def test_app_error_handler_logs_redacted_event_for_each_method(self):
        for method in ("GET", "POST", "PUT"):
            with self.subTest(method=method):
                logger = Mock()
                transport = Mock()
                handler = object.__new__(server.HTTP_API.request_handler_class())
                handler.path = "/api/synthetic?private=value"
                handler.request_id = "request-1"
                handler.dependencies = SimpleNamespace(
                    logger=logger,
                    redact_text=lambda value: value,
                    response_transport=transport,
                )
                handler._send_app_error(AppError(503, "synthetic failure"), method)
                logger.error.assert_called_once()
                event = logger.error.call_args.kwargs["extra"]
                self.assertEqual(event["event"], "http_app_error")
                self.assertEqual(event["context"]["method"], method)
                self.assertEqual(
                    event["context"],
                    {"method": method, "status": 503, "request_id": "request-1"},
                )
                self.assertNotIn("synthetic failure", repr(logger.error.call_args))
                self.assertNotIn("private", repr(event))

    def test_provider_auth_error_does_not_receive_session_challenge(self):
        transport = Mock()
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = "/api/synthetic"
        handler.request_id = "request-provider"
        handler.dependencies = SimpleNamespace(
            logger=Mock(),
            redact_text=lambda value: value,
            response_transport=transport,
        )
        handler._send_app_error(
            AppError(
                401,
                "Provider authentication failed",
                reason="authentication_or_permission",
                upstream_status=401,
            ),
            "POST",
        )
        self.assertEqual(transport.send_json.call_args.args[1], 502)
        self.assertIsNone(transport.send_json.call_args.args[3])

    def test_missing_request_id_is_omitted_from_error_response(self):
        transport = Mock()
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = "/api/synthetic"
        handler.dependencies = SimpleNamespace(
            logger=Mock(),
            redact_text=lambda value: value,
            response_transport=transport,
        )

        handler._send_app_error(AppError(400, "Invalid"), "GET")

        self.assertNotIn("request_id", transport.send_json.call_args.args[2])

    def test_local_session_401_receives_session_challenge(self):
        transport = Mock()
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = "/api/synthetic"
        handler.request_id = "request-session"
        handler.dependencies = SimpleNamespace(
            logger=Mock(),
            redact_text=lambda value: value,
            response_transport=transport,
        )
        handler._send_app_error(AppError(401, "Login required"), "POST")
        self.assertEqual(transport.send_json.call_args.args[1], 401)
        self.assertEqual(
            transport.send_json.call_args.args[3], {"WWW-Authenticate": "Session"}
        )

    def test_http_api_keeps_dispatchers_shared_and_handler_configuration_lazy(
        self,
    ):
        first = server.HTTP_API.request_handler_class()
        with patch.object(server.APP, "app_version", "synthetic-next"):
            second = server.HTTP_API.request_handler_class()

        self.assertIsNot(first, second)
        self.assertEqual(first.server_version, f"Pacecraft/{server.APP_VERSION}")
        self.assertEqual(second.server_version, "Pacecraft/synthetic-next")
        self.assertIs(first.dependencies.route_table, server.HTTP_API.route_table)
        self.assertIs(second.dependencies.route_table, server.HTTP_API.route_table)
        self.assertIs(
            first.dependencies.response_transport, server.HTTP_API.response_transport
        )
        self.assertIsNot(first.static_asset_service, second.static_asset_service)

    def test_mixed_edit_scope_cannot_authorize_unrelated_existing_unit(self):
        first = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Ride",
                "name": "First",
                "description": "- 20m 60% easy",
            }
        )
        second = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=2)
                ).isoformat(),
                "sport": "Run",
                "name": "Second",
                "description": "- 20m 60% easy",
            }
        )
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"planned_unit:{first['id']}"],
        }
        with self.assertRaises(AppError) as error:
            server.COACH_TOOL_DISPATCH.service().execute(
                "apply_training_changes",
                {
                    "changes": [
                        {"local_id": second["id"], "action": "archive"},
                        {
                            "action": "create",
                            "date": (
                                server.ATHLETE_CLOCK.now().date() + timedelta(days=3)
                            ).isoformat(),
                            "sport": "Run",
                            "name": "Recovery",
                            "description": "- 20m 60% easy",
                            "duration_minutes": 20,
                            "target": "AUTO",
                            "rationale": "Recovery",
                        },
                    ]
                },
                intent=intent,
                conversation_id="conversation-mixed-scope",
                client_turn_id="turn-mixed-scope",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        self.assertIsNotNone(
            next(
                item
                for item in server.PLANNING_DATA.planned_unit().list()
                if item["id"] == second["id"]
            )
        )

    def test_local_public_state_does_not_fetch_weather(self):
        server.ATHLETE_DATA.profile().save({"weather_location": "Berlin"})
        with patch.object(
            weather_provider.WeatherClient,
            "fetch",
            side_effect=AssertionError("weather must stay local"),
        ):
            configured = server.PUBLIC_STATE.bootstrap_service().read()["configured"]
            weather = server.PUBLIC_STATE.weather_state_service().state(local_only=True)
        self.assertTrue(configured["weather"])
        self.assertTrue(weather["loading"])

    def test_session_cookies_secure_flag_is_configurable_without_changing_csrf_visibility(
        self,
    ):
        insecure = server.session_auth_service().session_cookie_headers(
            "session-token", "csrf-token"
        )
        self.assertNotIn("; Secure", insecure[0])
        self.assertNotIn("; Secure", insecure[1])
        self.assertIn("HttpOnly", insecure[0])
        self.assertNotIn("HttpOnly", insecure[1])
        with patch.object(
            server.CONFIG_HOLDER,
            "value",
            replace(server.CONFIG_HOLDER.value, secure_cookies=True),
        ):
            secure = server.session_auth_service().session_cookie_headers(
                "session-token", "csrf-token"
            )
        self.assertIn("; Secure", secure[0])
        self.assertIn("; Secure", secure[1])
        self.assertIn("Max-Age=2592000", secure[0])

    def test_authenticated_session_throttles_last_seen_without_extending_fixed_expiry(
        self,
    ):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies=""):
                self.headers = {"Cookie": cookies}

        token = create_test_session(server)
        auth = server.session_auth_service()
        token_hash = auth.session_token_hash(token)
        old_seen = "2020-01-01T00:00:00+00:00"
        with server.database_manager().unit_of_work() as db:
            original = db.execute(
                "SELECT expires_at FROM sessions WHERE token_hash=?", (token_hash,)
            ).fetchone()["expires_at"]
            db.execute(
                "UPDATE sessions SET last_seen=? WHERE token_hash=?",
                (old_seen, token_hash),
            )

        first = auth.authenticated_session(Handler(f"ic_session={token}"))
        with server.database_manager().unit_of_work() as db:
            touched = db.execute(
                "SELECT expires_at, last_seen FROM sessions WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        second = auth.authenticated_session(Handler(f"ic_session={token}"))
        with server.database_manager().unit_of_work() as db:
            unchanged = db.execute(
                "SELECT expires_at, last_seen FROM sessions WHERE token_hash=?",
                (token_hash,),
            ).fetchone()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(touched["expires_at"], original)
        self.assertNotEqual(touched["last_seen"], old_seen)
        self.assertEqual(unchanged["expires_at"], original)
        self.assertEqual(unchanged["last_seen"], touched["last_seen"])

    def test_expired_session_is_rejected_and_removed_immediately(self):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies=""):
                self.headers = {"Cookie": cookies}

        token = create_test_session(server)
        auth = server.session_auth_service()
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE sessions SET expires_at=? WHERE token_hash=?",
                (time.time() - 1, auth.session_token_hash(token)),
            )
        self.assertIsNone(auth.authenticated_session(Handler(f"ic_session={token}")))
        with server.database_manager().unit_of_work() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT token_hash FROM sessions WHERE token_hash=?",
                    (auth.session_token_hash(token),),
                ).fetchone()
            )

    def test_expired_session_cleanup_is_bounded_and_periodic(self):
        with server.database_manager().unit_of_work() as db:
            for index in range(http_auth.SESSION_CLEANUP_BATCH_SIZE + 1):
                db.execute(
                    "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (f"expired-{index}", f"csrf-{index}", 0, "now", "now"),
                )
            auth = server.session_auth_service()
            deleted = auth.cleanup_expired_sessions(db, time.time(), force=True)
            remaining = db.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()[
                "count"
            ]
        self.assertEqual(deleted, http_auth.SESSION_CLEANUP_BATCH_SIZE)
        self.assertEqual(remaining, 1)

    def test_parallel_authenticated_requests_share_a_valid_session(self):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies=""):
                self.headers = {"Cookie": cookies}

        token = create_test_session(server)
        cookies = f"ic_session={token}"
        barrier = threading.Barrier(8)
        results = []
        errors = []

        def authenticate():
            try:
                barrier.wait(timeout=5)
                results.append(
                    server.session_auth_service().authenticated_session(
                        Handler(cookies)
                    )
                )
            except Exception as exc:  # noqa: BLE001 - Collect every worker-thread failure for the main-thread assertion.
                errors.append(exc)

        threads = [threading.Thread(target=authenticate) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result is not None for result in results))

    def test_csrf_rejects_missing_or_foreign_token(self):
        class MissingTokenHandler:
            headers: ClassVar = {}

        with self.assertRaises(AppError) as missing:
            server.session_auth_service().require_csrf(
                MissingTokenHandler(),
                {
                    "csrf_hash": server.session_auth_service().session_token_hash(
                        "expected"
                    )
                },
            )
        self.assertEqual(missing.exception.status, 403)

        class Handler:
            headers: ClassVar = {"X-CSRF-Token": "foreign"}

        with self.assertRaises(AppError) as foreign:
            server.session_auth_service().require_csrf(
                Handler(),
                {
                    "csrf_hash": server.session_auth_service().session_token_hash(
                        "expected"
                    )
                },
            )
        self.assertEqual(foreign.exception.status, 403)

    def test_logout_removes_session_immediately(self):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies=""):
                self.headers = {"Cookie": cookies}

        token = create_test_session(server)
        auth = server.session_auth_service()
        auth.logout_user(Handler(f"ic_session={token}"))
        self.assertIsNone(auth.authenticated_session(Handler(f"ic_session={token}")))

    def test_public_states_keep_empty_usage_when_openai_is_not_configured(self):
        config = replace(server.CONFIG_HOLDER.value, openai_api_key="")
        with patch.object(server.CONFIG_HOLDER, "value", config):
            bootstrap = server.PUBLIC_STATE.bootstrap_service().read()

        self.assertEqual(bootstrap["usage"]["requests"], 0)
        self.assertEqual(bootstrap["usage"]["status"], {})
        self.assertEqual(bootstrap["usage"]["rate_limits"], {})

    def test_public_state_exposes_daily_planning_context(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot_seed.save_snapshot(
            server.SYNC_PERSISTENCE.state_repository(),
            {
                "synced_at": "now",
                "athlete": {},
                "recent_activities": [],
                "recent_wellness": [],
                "upcoming_calendar": [
                    {"name": "Locker", "start_date_local": f"{today}T08:00:00"}
                ],
            },
        )
        server.ATHLETE_DATA.checkin().save({"checkin_date": today, "motivation": 8})
        state = server.PUBLIC_STATE.plan_state_service().read(local_only=True)
        self.assertEqual(state["daily_planning_context"][0]["date"], today)
        self.assertEqual(state["daily_planning_context"][0]["checkin"]["motivation"], 8)

    def test_chat_history_pagination_and_bounded_search_use_message_id_cursor(self):
        for index in range(5):
            server.APP.coach_conversation.message_service().add(
                "user", f"searchable {index}"
            )
        page_service = server.HTTP_API.chat_history_page_service()
        first = page_service.page(limit=2)
        second = page_service.page(cursor=first["next_cursor"], limit=2)
        page_ids = [item["id"] for item in first["messages"] + second["messages"]]
        page_contents = [
            item["content"] for item in first["messages"] + second["messages"]
        ]
        self.assertEqual(
            set(page_contents),
            {"searchable 1", "searchable 2", "searchable 3", "searchable 4"},
        )
        self.assertEqual(len(page_ids), len(set(page_ids)))
        search = page_service.page(limit=10, search="searchable 3")
        self.assertEqual(
            [item["content"] for item in search["messages"]], ["searchable 3"]
        )

    def test_chat_history_search_escapes_like_metacharacters(self):
        contents = (
            "literal percent%marker",
            "literal percentXmarker",
            "literal underscore_marker",
            "literal underscoreXmarker",
            r"literal backslash\marker",
            "literal backslashmarker",
        )
        for content in contents:
            server.APP.coach_conversation.message_service().add("user", content)

        page_service = server.HTTP_API.chat_history_page_service()
        for search_term, expected in (
            ("percent%marker", "literal percent%marker"),
            ("underscore_marker", "literal underscore_marker"),
            (r"backslash\marker", r"literal backslash\marker"),
        ):
            with self.subTest(search_term=search_term):
                page = page_service.page(search=search_term)
                self.assertEqual(
                    [item["content"] for item in page["messages"]], [expected]
                )

    def test_chat_reset_changes_history_generation(self):
        before = server.HTTP_API.chat_history_page_service().page()["generation"]
        server.APP.coach_conversation.reset_service().reset()
        self.assertNotEqual(
            server.HTTP_API.chat_history_page_service().page()["generation"], before
        )

    def test_coach_and_http_library_views_include_the_same_active_templates(self):
        with server.database_manager().unit_of_work() as db:
            db.executemany(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (
                        f"archived-{index:03d}",
                        f"archived-{index:03d}",
                        json.dumps(
                            {
                                "id": f"archived-{index:03d}",
                                "type": "Ride",
                                "name": f"000 archived {index:03d}",
                                "archived": True,
                            }
                        ),
                        "synthetic-now",
                    )
                    for index in range(100)
                ]
                + [
                    (
                        "active-after-limit",
                        "active-after-limit",
                        json.dumps(
                            {
                                "id": "active-after-limit",
                                "type": "Ride",
                                "name": "zzz active",
                            }
                        ),
                        "synthetic-now",
                    )
                ],
            )

        coach_entries = server.PLANNING_DATA.workout_library().list(limit=100)
        http_entries = server.HTTP_API.library_page_service().page(limit=100)[
            "workouts"
        ]
        self.assertEqual(
            [entry["id"] for entry in coach_entries],
            [entry["id"] for entry in http_entries],
        )
        self.assertEqual(
            [entry["id"] for entry in coach_entries], ["active-after-limit"]
        )

    def test_library_http_pagination_reaches_every_active_template_beyond_1000(self):
        records = [
            {"id": f"template-{i:04}", "name": f"Synthetic {i:04}", "type": "Ride"}
            for i in range(1001)
        ]
        records += [
            {"id": "archived", "name": "Archived", "archived": True},
            {"id": "dated", "name": "Dated", "date": "2026-09-09"},
        ]
        with server.database_manager().unit_of_work() as db:
            db.executemany(
                "INSERT INTO workout_library(id,local_id,payload,updated_at) VALUES (?,?,?,?)",
                [
                    (item["id"], item["id"], json.dumps(item), runtime_clock.utc_now())
                    for item in records
                ],
            )
        token = create_test_session(server)
        # This temporary SQLite fixture exercises pagination and real session
        # authentication; secure startup has separate SQLCipher integration tests.
        startup = patch.object(
            server.app_config, "security_configuration_error", return_value=None
        )
        startup.start()
        self.addCleanup(startup.stop)
        httpd = http_server_module.CoachHTTPServer(
            ("127.0.0.1", 0), server.HTTP_API.request_handler_class()
        )
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", httpd.server_port, timeout=5
        )
        ids, cursor = [], None
        try:
            for _ in range(12):
                query = {"limit": 100}
                if cursor:
                    query["cursor"] = cursor
                connection.request(
                    "GET",
                    "/api/library?" + urlencode(query),
                    headers={"Cookie": f"ic_session={token}"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                page = json.loads(response.read())
                self.assertLessEqual(len(page["workouts"]), 100)
                ids.extend(item["id"] for item in page["workouts"])
                cursor = page["next_cursor"]
                if not cursor:
                    break
        finally:
            connection.close()
            httpd.shutdown()
            worker.join(5)
            httpd.server_close()
        self.assertIsNone(cursor)
        self.assertEqual(ids, [f"template-{i:04}" for i in range(1001)])

    def test_bootstrap_is_bounded_and_excludes_history_collections(self):
        today = server.ATHLETE_CLOCK.now().date()
        snapshot_seed.save_snapshot(
            server.SYNC_PERSISTENCE.state_repository(),
            {
                "synced_at": "now",
                "athlete": {},
                "recent_wellness": [],
                "upcoming_calendar": [],
                "recent_activities": [
                    {
                        "id": f"activity-{index}",
                        "type": "Ride",
                        "start_date_local": today.isoformat(),
                    }
                    for index in range(500)
                ],
            },
        )
        for index in range(500):
            server.APP.coach_conversation.message_service().add(
                "user", f"message {index}"
            )
        bootstrap = server.PUBLIC_STATE.bootstrap_service().read()
        self.assertEqual(
            list(bootstrap),
            [
                "state_versions",
                "app",
                "messages",
                "messages_next_cursor",
                "library",
                "activities",
                "planned",
                "calendar",
                "planning_compliance",
                "weather",
                "profile",
                "competitions",
                "checkins",
                "local_feedback",
                "activity_feedback",
                "planning",
                "external_calendar",
                "daily_planning_context",
                "performance",
                "garmin",
                "diagnostic_capture",
                "intervals",
                "provider_freshness",
                "provider_ids",
                "provider_labels",
                "garmin_sync",
                "provider_resync",
                "sync",
                "library_sync",
                "sync_settings",
                "calendar_display",
                "morning_checkin",
                "coach_quick_actions",
                "model",
                "service_tier",
                "thinking_level",
                "configured",
                "wahoo",
                "credentials",
                "usage",
                "usage_month",
                "provider_status",
                "threshold_warnings",
            ],
        )
        self.assertEqual(len(bootstrap["messages"]), 100)
        self.assertEqual(bootstrap["activities"], [])
        self.assertIn("activities", bootstrap["state_versions"])
        self.assertIn("garmin", bootstrap["state_versions"])
        self.assertLess(len(json.dumps(bootstrap, ensure_ascii=False)), 21_000)

    def test_bootstrap_never_refreshes_provider_network(self):
        with (
            patch.object(
                server.PROVIDER_TRANSPORT.json_http_client(),
                "request",
                side_effect=AssertionError("network"),
            ),
            patch.object(
                provider_http,
                "external_call",
                side_effect=AssertionError("network"),
            ),
        ):
            bootstrap = server.PUBLIC_STATE.bootstrap_service().read()
        self.assertEqual(bootstrap["provider_labels"]["intervals"], "Intervals.icu")
        self.assertEqual(bootstrap["provider_labels"]["garmin"], "Garmin")
        self.assertEqual(
            bootstrap["provider_ids"],
            {"intervals": "intervals", "garmin": "garmin", "wahoo": "wahoo"},
        )

    def test_state_events_report_missed_retention_and_redact_content(self):
        runtime_events.STATE_EVENT_BUFFER.clear()
        for index in range(501):
            runtime_events.STATE_EVENT_BUFFER.publish(
                "job",
                {
                    "job_id": f"job-{index}",
                    "status": "running",
                    "progress": {"completed": index, "total": 501},
                },
            )
        gap = runtime_events.STATE_EVENT_BUFFER.since(0)
        self.assertTrue(gap["gap"])
        self.assertEqual(gap["events"], [])
        current = runtime_events.STATE_EVENT_BUFFER.since(gap["latest_event_id"] - 1)
        self.assertFalse(current["gap"])
        self.assertEqual(len(current["events"]), 1)
        self.assertNotIn("athlete content", json.dumps(current))

    def test_http_response_helpers_are_dependency_light_and_preserve_headers(self):
        from backend.http_api import responses

        source = Path(responses.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)
        self.assertEqual(responses.json_bytes({"text": "ä"}), b'{"text": "\xc3\xa4"}')
        self.assertEqual(
            list(
                responses.header_items(
                    {"Set-Cookie": ["one", "two"], "X-Test": "value"}
                )
            ),
            [("Set-Cookie", "one"), ("Set-Cookie", "two"), ("X-Test", "value")],
        )
        self.assertEqual(
            responses.response_headers("application/json", 12),
            (
                ("Content-Type", "application/json"),
                ("Content-Length", "12"),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
            ),
        )
        self.assertEqual(
            responses.session_cookies(
                "session", "csrf", "token", "csrf-token", ttl_seconds=60, secure=True
            ),
            [
                "session=token; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=60",
                "csrf=csrf-token; Path=/; SameSite=Strict; Secure; Max-Age=60",
            ],
        )
        self.assertEqual(
            responses.session_cookies(
                "session", "csrf", "token", "csrf-token", ttl_seconds=60, clear=True
            ),
            [
                "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                "csrf=; Path=/; SameSite=Strict; Max-Age=0",
            ],
        )

    def test_http_request_helpers_are_dependency_light_and_preserve_limits(self):
        from backend.http_api import requests

        source = Path(requests.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)
        headers = {"Content-Length": "7"}
        self.assertEqual(
            requests.read_body(headers, BytesIO(b"payload").read, 10, error=AppError),
            b"payload",
        )
        self.assertEqual(
            requests.read_json(
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": "12",
                },
                BytesIO(b'{"ok": true}').read,
                100,
                error=AppError,
            ),
            {"ok": True},
        )
        self.assertEqual(
            requests.read_audio_body(
                {"Content-Type": "audio/webm;codecs=opus", "Content-Length": "5"},
                BytesIO(b"audio").read,
                allowed_types={"audio/webm": ".webm"},
                normalize_type=lambda value: value.split(";", 1)[0],
                max_bytes=10,
                error=AppError,
            ),
            b"audio",
        )
        with self.assertRaises(AppError) as oversized:
            requests.read_body(
                {"Content-Length": "11"},
                BytesIO(b"x" * 11).read,
                10,
                error=AppError,
            )
        self.assertEqual(oversized.exception.status, 413)
        with self.assertRaises(AppError) as malformed:
            requests.read_json(
                {"Content-Type": "application/json", "Content-Length": "9"},
                BytesIO(b"not-json!").read,
                100,
                error=AppError,
            )
        self.assertEqual(malformed.exception.status, 400)
        with self.assertRaises(AppError) as wrong_type:
            requests.read_json(
                {"Content-Type": "text/plain", "Content-Length": "7"},
                BytesIO(b'{"ok":1}').read,
                100,
                error=AppError,
            )
        self.assertEqual(wrong_type.exception.status, 415)
        with self.assertRaises(AppError) as non_object:
            requests.read_json(
                {"Content-Type": "application/json", "Content-Length": "2"},
                BytesIO(b"[]").read,
                100,
                error=AppError,
            )
        self.assertEqual(non_object.exception.status, 400)
        with self.assertRaises(AppError) as incomplete:
            requests.read_audio_body(
                {"Content-Type": "audio/webm", "Content-Length": "5"},
                BytesIO(b"aud").read,
                allowed_types={"audio/webm": ".webm"},
                normalize_type=lambda value: value.split(";", 1)[0],
                max_bytes=10,
                error=AppError,
            )
        self.assertEqual(incomplete.exception.status, 400)

    def test_streamed_body_checks_limits_before_reading_and_bounds_each_chunk(self):
        from backend.http_api import requests

        reads: list[int] = []
        source = BytesIO(b"0123456789")

        def read(size: int) -> bytes:
            reads.append(size)
            return source.read(size)

        with self.assertRaises(AppError) as oversized:
            requests.read_body_stream(
                {"Content-Length": "11"}, read, 10, error=AppError
            )
        self.assertEqual(oversized.exception.status, 413)
        self.assertEqual(reads, [])

        chunks = requests.read_body_stream(
            {"Content-Length": "10"}, read, 10, error=AppError, chunk_size=4
        )
        self.assertEqual(reads, [])
        self.assertEqual(list(chunks), [b"0123", b"4567", b"89"])
        self.assertEqual(reads, [4, 4, 2])

        truncated = requests.read_body_stream(
            {"Content-Length": "10"},
            BytesIO(b"01234").read,
            10,
            error=AppError,
            chunk_size=4,
        )
        with self.assertRaises(AppError) as incomplete:
            list(truncated)
        self.assertEqual(incomplete.exception.status, 400)

    def test_body_battery_only_error_does_not_degrade_garmin_public_state(self):
        server.key_value_service().set(
            "last_garmin_error",
            json.dumps(
                [
                    {
                        "source": "body_battery",
                        "message": "optional request unavailable",
                    },
                ]
            ),
        )

        self.assertIsNone(
            server.GARMIN_ASSEMBLY.projection_service().public_state()["last_error"]
        )

    def test_provider_authentication_errors_do_not_use_the_session_status(self):
        provider_error = AppError(
            401,
            "OpenAI key invalid.",
            reason="authentication_or_permission",
            upstream_status=401,
        )
        self.assertEqual(public_error_contract(provider_error), (502, "upstream_auth"))
        self.assertEqual(
            public_error_contract(AppError(401, "Anmeldung erforderlich."))[0],
            401,
        )

    def test_http_json_preserves_empty_body_and_oversized_response_contracts(self):
        class EmptyResponse:
            status = 204
            headers: ClassVar = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b""

        with patch.object(
            server.PROVIDER_TRANSPORT.json_http_client(),
            "opener",
            return_value=EmptyResponse(),
        ):
            self.assertIsNone(
                server.PROVIDER_TRANSPORT.json_http_client().request(
                    "DELETE",
                    "https://intervals.icu/api/v1/athlete/0",
                    service="intervals",
                )
            )

        class OversizedResponse(EmptyResponse):
            status = 200

            def read(self, *_args):
                return b"1234"

        with (
            patch.object(
                server.PROVIDER_TRANSPORT.json_http_client(), "max_response_bytes", 3
            ),
            patch.object(
                server.PROVIDER_TRANSPORT.json_http_client(),
                "opener",
                return_value=OversizedResponse(),
            ),
            self.assertRaises(AppError) as raised,
        ):
            server.PROVIDER_TRANSPORT.json_http_client().request(
                "GET", "https://intervals.icu/api/v1/athlete/0", service="intervals"
            )
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(
            raised.exception.message, "Die Antwort des externen Dienstes ist zu groß."
        )

    def test_transcribe_audio_sends_bounded_multipart_request(self):
        captured = {}

        def fake_http_json(
            method,
            url,
            payload=None,
            headers=None,
            timeout=45,
            service=None,
            raw_body=None,
            content_type=None,
        ):
            captured.update(
                {
                    "method": method,
                    "url": url,
                    "payload": payload,
                    "headers": headers,
                    "timeout": timeout,
                    "service": service,
                    "raw_body": raw_body,
                    "content_type": content_type,
                }
            )
            return {"text": "Wie soll ich morgen trainieren?"}

        audio = b"fake-webm-audio"
        with (
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(
                    server.CONFIG_HOLDER.value,
                    openai_api_key="test-key",
                    openai_base_url="https://foundry.example.invalid/openai/v1/",
                ),
            ),
            patch.object(
                server.PROVIDER_TRANSPORT.json_http_client(),
                "request",
                side_effect=fake_http_json,
            ),
        ):
            result = _transcribe_via_http_route(audio, "audio/webm;codecs=opus")

        self.assertEqual(result, {"transcript": "Wie soll ich morgen trainieren?"})
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["url"],
            "https://foundry.example.invalid/openai/v1/audio/transcriptions",
        )
        self.assertEqual(captured["service"], "openai")
        self.assertEqual(captured["timeout"], 90)
        self.assertIsNone(captured["payload"])
        self.assertIn("multipart/form-data; boundary=", captured["content_type"])
        self.assertIn(b'name="model"', captured["raw_body"])
        self.assertIn(b"gpt-transcribe", captured["raw_body"])
        self.assertIn(audio, captured["raw_body"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")

    def test_transcribe_audio_rejects_unknown_format_and_oversized_audio(self):
        config = replace(server.CONFIG_HOLDER.value, openai_api_key="test-key")
        with patch.object(server.CONFIG_HOLDER, "value", config):
            with self.assertRaises(AppError) as unsupported:
                _transcribe_via_http_route(b"audio", "audio/flac")
            with self.assertRaises(AppError) as oversized:
                _transcribe_via_http_route(
                    b"x" * (server.MAX_AUDIO_BODY_BYTES + 1), "audio/webm"
                )
        self.assertEqual(unsupported.exception.status, 415)
        self.assertEqual(oversized.exception.status, 413)

    def test_background_coach_job_is_persisted_and_session_scoped(self):
        job = server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Erstelle einen Trainingsplan für die nächsten 2 Wochen.",
            "turn-background-persisted",
            "csrf-background-owner",
            operation_id="operation-background-persisted",
        )
        self.assertEqual(job["status"], "queued")
        status = server.COACH_BACKGROUND_JOBS.job_submission_service().stream_status(
            "csrf-background-owner"
        )
        self.assertEqual(status["mode"], "background")
        self.assertEqual(status["operation_id"], "operation-background-persisted")
        self.assertEqual(
            server.COACH_BACKGROUND_JOBS.job_submission_service().stream_status(
                "csrf-other"
            ),
            {"status": "idle", "operation_id": None},
        )
        with server.database_manager().unit_of_work() as db:
            command = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-background-persisted'"
            ).fetchone()
            user_message = db.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(command["status"], "queued")
        self.assertNotIn("csrf-background-owner", command["receipt"])
        self.assertEqual(user_message["role"], "user")
        self.assertIn("2 Wochen", user_message["content"])

    def test_background_submission_atomically_allows_only_one_active_turn_per_session(
        self,
    ):
        service = server.COACH_BACKGROUND_JOBS.job_submission_service()
        original_active = service.active
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def synchronized_active(session_csrf_hash, operation_id=None):
            result = original_active(session_csrf_hash, operation_id)
            barrier.wait(timeout=5)
            return result

        def submit(client_turn_id):
            try:
                results.append(
                    service.enqueue(
                        "Erstelle eine längere Planung",
                        client_turn_id,
                        "csrf-background-concurrent-session",
                        operation_id=f"operation-{client_turn_id}",
                    )
                )
            except AppError as error:
                errors.append(error)

        registry = coach_streams.CHAT_STREAM_REGISTRY
        with (
            patch.object(service, "active", side_effect=synchronized_active),
            patch.object(runtime_events.STATE_EVENT_BUFFER, "publish"),
            patch.object(registry, "set_background_event"),
            patch.object(server.COACH_JOB_WORKER.wake_event, "set"),
        ):
            threads = [
                threading.Thread(target=submit, args=(turn_id,))
                for turn_id in ("turn-background-race-a", "turn-background-race-b")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AppError)
        self.assertEqual(errors[0].reason, "chat_already_running")
        with server.database_manager().unit_of_work() as db:
            commands = db.execute(
                "SELECT client_turn_id, status FROM coach_commands "
                "WHERE client_turn_id IN (?, ?)",
                ("turn-background-race-a", "turn-background-race-b"),
            ).fetchall()
            messages = db.execute(
                "SELECT client_turn_id FROM messages WHERE client_turn_id IN (?, ?)",
                ("turn-background-race-a", "turn-background-race-b"),
            ).fetchall()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["status"], "queued")
        self.assertEqual(len(messages), 1)

    def test_public_state_exposes_completed_and_planned_activity_tabs(self):
        server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Ride",
                "name": "Intervalle",
                "description": "- 30m Z2",
                "duration_minutes": 30,
            }
        )
        store_garmin_activities(
            server,
            [
                {
                    "activityId": "run-1",
                    "activityName": "Morgenlauf",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-08-25 07:00:00",
                }
            ],
        )
        state = server.PUBLIC_STATE.bootstrap_service().read()
        state["activities"] = server.ACTIVITY_READS.activity_read().page(
            today=server.ATHLETE_CLOCK.now().date()
        )["activities"]
        self.assertEqual(state["app"]["name"], "Pacecraft · AI Coach")
        self.assertEqual(state["app"]["version"], server.APP_VERSION)
        self.assertEqual(state["activities"][0]["name"], "Morgenlauf")
        self.assertEqual(state["planned"][0]["name"], "Intervalle")
        self.assertEqual(
            state["calendar_display"], {"past_weeks": 1, "future_weeks": 4}
        )

    def test_json_response_ignores_client_disconnect(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.request_id = "request-1"
        handler.command = "GET"
        handler.path = "/api/state"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=BrokenPipeError())
        handler.wfile = Mock()
        handler.log_client_disconnect = Mock()

        server.HTTP_API.request_handler_class().send_json(
            handler, 200, {"status": "ok"}
        )

        handler.log_client_disconnect.assert_called_once_with()
        handler.wfile.write.assert_not_called()

    def test_response_transport_uses_redacted_application_logger(self):
        self.assertIs(response_transport.LOGGER, server.LOGGER)

    def test_json_response_disconnect_logs_response_metadata(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.request_id = "request-2"
        handler.command = "GET"
        handler.path = "/api/activities"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=ConnectionResetError())
        handler.wfile = Mock()

        with patch.object(server.LOGGER, "info") as logger:
            server.HTTP_API.request_handler_class().send_json(
                handler, 200, {"activities": []}
            )

        context = logger.call_args.kwargs["extra"]["context"]
        self.assertEqual(context["method"], "GET")
        self.assertEqual(context["path"], "/api/activities")
        self.assertEqual(context["request_id"], "request-2")
        self.assertEqual(context["response_status"], 200)
        self.assertEqual(
            context["response_bytes"], len(responses.json_bytes({"activities": []}))
        )
        self.assertEqual(context["error_type"], "ConnectionResetError")
        self.assertGreaterEqual(context["response_duration_ms"], 0)

    def test_intervals_public_state_follows_the_output_stamps(self):
        config = replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key")
        keys = (
            "intervals_last_output_ok_at",
            "intervals_last_output_failed_at",
            "last_library_push_at",
            "last_library_sync_error",
        )

        def clear():
            for key in keys:
                server.key_value_service().set(key, "")
            with server.database_manager().unit_of_work() as db:
                db.execute("DELETE FROM sync_jobs WHERE requested_by = 'test'")

        def read_state(**stamps):
            for key, value in stamps.items():
                server.key_value_service().set(f"intervals_last_output_{key}_at", value)
            with patch.object(server.CONFIG_HOLDER, "value", config):
                return server.PUBLIC_STATE.bootstrap_service().read()["intervals"]

        clear()
        self.addCleanup(clear)
        # A failed job of the retired ingest says nothing about the output.
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO sync_jobs(id, provider, type, status, payload, "
                "requested_by, finished_at, created_at, updated_at) "
                "VALUES ('old-ingest', 'intervals', 'refresh', 'failed', '{}', "
                "'test', '2026-09-05T08:00:00+00:00', '2026-09-05T08:00:00+00:00', "
                "'2026-09-05T08:00:00+00:00')"
            )
        self.assertEqual(read_state()["state"], "configured")
        # A plan export stamps the card; a success from months ago stays connected.
        state = read_state(ok="2026-01-01T08:00:00+00:00")
        self.assertEqual(state["state"], "connected")
        self.assertEqual(state["last_used_at"], "2026-01-01T08:00:00+00:00")
        self.assertIsNone(state["library_sync"]["last_sync_at"])
        self.assertEqual(
            read_state(failed="2026-09-02T08:00:00+00:00")["state"], "error"
        )
        self.assertEqual(
            read_state(ok="2026-09-03T08:00:00+00:00")["state"], "connected"
        )
        # An old library error text never outranks a later success.
        server.key_value_service().set("last_library_sync_error", "alt")
        self.assertEqual(read_state()["state"], "connected")
        # An unreadable stamp is ignored instead of breaking the bootstrap.
        server.key_value_service().set("last_library_sync_error", "")
        self.assertEqual(
            read_state(ok="kaputt", failed="kaputt")["state"], "configured"
        )

    def test_readiness_handler_composition_preserves_status_and_json_contract(self):
        ready = {
            "status": "ready",
            "ready": True,
            "checks": {
                "database": True,
                "schema": True,
                "data_directory": True,
                "maintenance": True,
            },
            "maintenance": {"active": False},
        }
        not_ready = {
            "status": "not_ready",
            "ready": False,
            "checks": {
                "database": True,
                "schema": True,
                "data_directory": True,
                "maintenance": False,
            },
            "maintenance": {"active": True},
        }
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.send_json = Mock()

        original_manager = server.database_manager()
        switched_manager = Mock()
        seen_managers = []

        def projected_state(service):
            seen_managers.append(service._manager_factory())
            return ready if len(seen_managers) == 1 else not_ready

        with (
            patch.object(
                server.APP,
                "database",
                side_effect=[original_manager, switched_manager],
            ),
            patch.object(
                ReadinessService, "state", autospec=True, side_effect=projected_state
            ),
        ):
            self.assertTrue(
                dispatch_route(
                    server.HTTP_API.public_get_routes, handler, "/api/readiness"
                )
            )
            self.assertTrue(
                dispatch_route(
                    server.HTTP_API.public_get_routes, handler, "/api/readiness"
                )
            )

        self.assertEqual(seen_managers, [original_manager, switched_manager])
        self.assertEqual(
            handler.send_json.call_args_list,
            [call(200, ready), call(503, not_ready)],
        )

    def test_readiness_handler_returns_503_when_manager_composition_fails(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.send_json = Mock()
        with (
            tempfile.TemporaryDirectory() as data_dir,
            patch.object(server, "DATA_DIR", Path(data_dir)),
            patch.object(
                server.APP, "database", side_effect=OSError("mount unavailable")
            ),
        ):
            self.assertTrue(
                dispatch_route(
                    server.HTTP_API.public_get_routes, handler, "/api/readiness"
                )
            )
        status, payload = handler.send_json.call_args.args
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["checks"]["database"])
        self.assertFalse(payload["checks"]["schema"])
        self.assertNotIn("mount unavailable", json.dumps(payload))

    def test_rate_limit_cleanup_removes_old_bounded_buckets(self):
        limiter = RateLimiter()
        limiter.buckets = {f"expired:{index}": [0.0] for index in range(101)}
        with patch("backend.http_api.rate_limit.time.monotonic", return_value=20 * 60):
            self.assertEqual(limiter.allow("fresh", 1, 60), (True, 60))
        self.assertNotIn("expired:0", limiter.buckets)
        self.assertIn("expired:100", limiter.buckets)
        self.assertIn("fresh", limiter.buckets)

    def test_rate_limiter_enforces_limit_retry_after_and_independent_keys(self):
        limiter = RateLimiter()
        with patch(
            "backend.http_api.rate_limit.time.monotonic",
            side_effect=(1000.0, 1002.0, 1002.0),
        ):
            self.assertEqual(limiter.allow("login:one", 1, 10), (True, 10))
            self.assertEqual(limiter.allow("login:one", 1, 10), (False, 8))
            self.assertEqual(limiter.allow("login:two", 1, 10), (True, 10))

    def test_api_auth_uses_rate_limiter_and_preserves_retry_response(self):
        handler = Mock(client_address=("203.0.113.7", 0))
        auth = server.session_auth_service()
        with (
            patch.object(
                server.app_config, "security_configuration_error", return_value=None
            ),
            patch.object(
                auth, "authenticated_session", return_value={"csrf_hash": "unused"}
            ),
            patch.object(
                RateLimiter, "allow", autospec=True, return_value=(False, 17)
            ) as rate_limit,
            self.assertRaises(AppError) as raised,
        ):
            auth.require_auth(handler)
        self.assertEqual(raised.exception.status, 429)
        self.assertIn("17 Sekunden", raised.exception.message)
        rate_limit.assert_called_once_with(
            http_auth.RATE_LIMITER, "api:203.0.113.7", 180, 60
        )

    def test_openai_rate_limit_headers_are_exposed_without_local_limits(self):
        class FakeResponse:
            status = 200
            headers: ClassVar = {
                "x-ratelimit-remaining-requests": "19",
                "x-ratelimit-remaining-tokens": "12000",
                "x-ratelimit-reset-requests": "30s",
            }

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, *args):
                return b"{}"

        with patch.object(
            server.PROVIDER_TRANSPORT.json_http_client(),
            "opener",
            return_value=FakeResponse(),
        ):
            server.PROVIDER_TRANSPORT.json_http_client().request(
                "POST",
                "https://api.openai.com/v1/responses",
                payload={},
                service="openai",
            )
        summary = server.provider_state_service().summary("openai")
        self.assertNotIn("request_limit", summary)
        self.assertNotIn("token_limit", summary)
        self.assertEqual(summary["rate_limits"]["remaining_requests"], "19")
        self.assertEqual(summary["rate_limits"]["remaining_tokens"], "12000")
        self.assertEqual(summary["status"]["state"], "ok")

    def test_responses_request_routes_openai_to_provider_client(self):
        request = ModelRequest(model="gpt-6-luna", instructions="")
        with patch.object(
            openai_requests.OpenAIResponsesClient,
            "responses",
            return_value={"output_text": "ok"},
        ) as responses:
            result = server.APP.coach_conversation.response_transport().request(request)
        self.assertEqual(result.text, "ok")
        responses.assert_called_once_with(request_payload(request))

    def test_responses_stream_request_routes_openai_to_provider_client(self):
        request = ModelRequest(model="gpt-6-luna", instructions="")
        cancel_event = threading.Event()
        on_delta = Mock()
        on_response_id = Mock()

        with patch.object(
            openai_stream.OpenAIStreamClient,
            "stream",
            return_value={"status": "completed"},
        ) as stream:
            result = server.APP.coach_conversation.response_transport().stream_request(
                request, on_delta, cancel_event, on_response_id
            )

        self.assertEqual(result.stop_reason, "completed")
        stream.assert_called_once_with(
            request_payload(request),
            on_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )

    def test_public_state_and_usage_workers_do_not_deadlock(self):
        # A state request owns the writer while a worker starts reading/updating
        # usage, then the request reads the state: the read must not queue
        # behind the worker, and the worker finishes once the writer is free.
        gate = server.database_manager()._writer_lock
        for update in (False, True):
            with self.subTest(update=update):
                errors = []

                with patch.object(
                    provider_http,
                    "urlopen",
                    side_effect=AssertionError("State must stay local"),
                ):
                    state = server.provider_state_service()

                    def worker(update=update, state=state, errors=errors):
                        try:
                            if update:
                                state.record_usage(
                                    "openai", {"usage": {"output_tokens": 2}}, "test"
                                )
                            else:
                                state.summary("openai")
                        except Exception as exc:  # noqa: BLE001 - Collect every worker-thread failure for the main-thread assertion.
                            errors.append(exc)

                    thread = threading.Thread(target=worker)
                    try:
                        with server.database_manager().unit_of_work():
                            thread.start()
                            if update:
                                deadline = time.monotonic() + 3
                                while (
                                    gate._foreground_waiting == 0
                                    and time.monotonic() < deadline
                                ):
                                    time.sleep(0.005)
                                self.assertEqual(gate._foreground_waiting, 1)
                            else:
                                # The usage summary is a pure reader read: it
                                # finishes while this thread owns the writer,
                                # never queueing.
                                thread.join(timeout=3)
                                self.assertFalse(thread.is_alive())
                                self.assertEqual(gate._foreground_waiting, 0)
                            self.assertIn(
                                "usage", server.PUBLIC_STATE.bootstrap_service().read()
                            )
                    finally:
                        thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])

    def test_activity_pagination_has_stable_cursor_without_duplicates(self):
        today = server.ATHLETE_CLOCK.now().date()
        store_garmin_activities(
            server,
            [
                {
                    "activityId": f"activity-{index}",
                    "activityName": f"Activity {index}",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": f"{today.isoformat()} 08:0{index}:00",
                }
                for index in range(5)
            ]
            + [
                {
                    "activityId": "old",
                    "activityName": "Old",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": "2000-01-01 08:00:00",
                }
            ],
        )
        service = server.ACTIVITY_READS.activity_read()
        first = service.page(limit=2, days=1, today=today)
        second = service.page(first["next_cursor"], 2, 1, today=today)
        third = service.page(second["next_cursor"], 2, 1, today=today)
        ids = [
            item["record_ids"]["garmin"]
            for page in (first, second, third)
            for item in page["activities"]
        ]
        self.assertEqual(
            ids, ["activity-4", "activity-3", "activity-2", "activity-1", "activity-0"]
        )
        self.assertIsNone(third["next_cursor"])

    def test_intervals_public_state_adopts_an_export_from_before_the_stamps(self):
        config = replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key")
        stamps = ("intervals_last_output_ok_at", "intervals_last_output_failed_at")

        def clear():
            for key in stamps:
                server.key_value_service().set(key, "")
            with server.database_manager().unit_of_work() as db:
                db.execute("DELETE FROM remote_links WHERE provider = 'intervals'")

        def link(local_id, synced_at):
            with server.database_manager().unit_of_work() as db:
                db.execute(
                    "INSERT INTO remote_links(entity_kind, local_id, provider, "
                    "remote_id, sync_state, last_synced_at) "
                    "VALUES ('planned_unit', ?, 'intervals', ?, 'synced', ?)",
                    (local_id, local_id, synced_at),
                )

        def read_state():
            with patch.object(server.CONFIG_HOLDER, "value", config):
                return server.PUBLIC_STATE.bootstrap_service().read()["intervals"]

        clear()
        self.addCleanup(clear)
        link("stamp-old", "2026-10-02T08:00:00+00:00")
        link("stamp-new", "2026-10-03T08:00:00+00:00")
        self.assertEqual(read_state()["state"], "configured")
        # The startup adopts the newest export once; a later failure still wins.
        server.SYNC_PERSISTENCE.state_repository().adopt_intervals_export_time()
        state = read_state()
        self.assertEqual(state["state"], "connected")
        self.assertEqual(state["last_used_at"], "2026-10-03T08:00:00+00:00")
        server.key_value_service().set(
            "intervals_last_output_failed_at", "2026-10-04T08:00:00+00:00"
        )
        self.assertEqual(read_state()["state"], "error")


if __name__ == "__main__":
    unittest.main()
