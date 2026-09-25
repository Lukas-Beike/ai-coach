"""Server integration tests for http."""

import json
import queue
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import call, Mock, patch
from urllib.error import HTTPError

from backend.coach import streams as coach_streams
from backend.errors import ClientDisconnected
from backend.http_api import auth as http_auth, readiness as readiness_module, response_transport, responses
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.readiness import ReadinessService
from backend.http_api.state_events_get import StateEventsGetRoutes
from backend.http_api.state_events_transport import StateEventTransport
from backend.providers import http as provider_http, weather as weather_provider
from backend.runtime import events as runtime_events, maintenance as runtime_maintenance
from server_test_support import _transcribe_via_http_route, create_test_session, server, ServerTestCase


class ServerHttpTests(ServerTestCase):

    def test_weather_handler_calls_public_weather_service_after_auth(self):
        handler = object.__new__(server.request_handler_class())
        handler.path = "/api/weather?local=1"
        handler.send_json = Mock()
        endpoint = Mock()
        endpoint.state.return_value = {"configured": True, "loading": True}

        auth = Mock()
        with patch.object(
            server.PLANNING_GET_ROUTES, "_session_auth_service", return_value=auth
        ) as auth_factory, patch.object(
            server.PLANNING_GET_ROUTES,
            "_public_weather_state_service",
            return_value=endpoint,
        ) as factory:
            self.assertTrue(server.PLANNING_GET_ROUTES.handle(handler, "/api/weather"))

        auth.require_auth.assert_called_once_with(handler)
        auth_factory.assert_called_once_with()
        factory.assert_called_once_with()
        endpoint.state.assert_called_once_with(local_only=True)
        handler.send_json.assert_called_once_with(
            200, {"configured": True, "loading": True}
        )

    def test_sync_post_handler_keeps_bodyless_routes_and_unknown_posts_transport_only(self):
        handler = object.__new__(server.request_handler_class())
        handler.read_json = Mock(return_value={"ignored": True})
        handler.send_json = Mock()
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-3"})
        with patch.object(server, "sync_command_endpoint", return_value=endpoint) as factory:
            self.assertFalse(server.SYNC_COMMAND_POST_ROUTE.handle(handler, "/api/unknown"))
            factory.assert_not_called()
            self.assertTrue(server.SYNC_COMMAND_POST_ROUTE.handle(handler, "/api/weather/sync"))
        handler.read_json.assert_not_called()
        endpoint.execute.assert_called_once_with("/api/weather/sync", None)
        handler.send_json.assert_called_once_with(202, {"id": "job-3"})

    def test_plan_handler_delegates_local_and_refresh_reads_to_service(self):
        for local_only in (True, False):
            with self.subTest(local_only=local_only):
                handler = object.__new__(server.request_handler_class())
                handler.path = "/api/plan?local=1" if local_only else "/api/plan"
                handler.send_json = Mock()
                service = Mock()
                service.read.return_value = {"plans": []}
                auth = Mock()
                with (
                    patch.object(
                        server.PLANNING_GET_ROUTES,
                        "_session_auth_service",
                        return_value=auth,
                    ) as auth_factory,
                    patch.object(
                        server.PLANNING_GET_ROUTES,
                        "_public_plan_state_service",
                        return_value=service,
                    ) as service_factory,
                ):
                    self.assertTrue(server.PLANNING_GET_ROUTES.handle(handler, "/api/plan"))
                auth.require_auth.assert_called_once_with(handler)
                auth_factory.assert_called_once_with()
                service_factory.assert_called_once_with()
                service.read.assert_called_once_with(local_only=local_only)
                handler.send_json.assert_called_once_with(200, {"plans": []})

    def test_mixed_edit_scope_cannot_authorize_unrelated_existing_unit(self):
        first = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "First", "description": "- 20m 60% easy",
        })
        second = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "sport": "Run", "name": "Second", "description": "- 20m 60% easy",
        })
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"planned_unit:{first['id']}"],
        }
        with self.assertRaises(server.AppError) as error:
            server.coach_tool_dispatch_service().execute(
                "apply_training_changes",
                {"changes": [{"local_id": second["id"], "action": "archive"}, {
                    "action": "create", "date": (date.today() + timedelta(days=3)).isoformat(),
                    "sport": "Run", "name": "Recovery", "description": "- 20m 60% easy",
                    "duration_minutes": 20, "target": "AUTO", "rationale": "Recovery",
                }]},
                intent=intent, conversation_id="conversation-mixed-scope", client_turn_id="turn-mixed-scope",
                session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        self.assertIsNotNone(next(item for item in server.planned_unit_service().list() if item["id"] == second["id"]))

    def test_local_public_state_does_not_fetch_weather(self):
        server.profile_service().save({"weather_location": "Berlin"})
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=AssertionError("weather must stay local")):
            state = server.public_state_service().read(local_only=True)
        self.assertTrue(state["configured"]["weather"])
        self.assertTrue(state["weather"]["loading"])

    def test_session_cookies_secure_flag_is_configurable_without_changing_csrf_visibility(self):
        insecure = server.session_auth_service().session_cookie_headers("session-token", "csrf-token")
        self.assertNotIn("; Secure", insecure[0])
        self.assertNotIn("; Secure", insecure[1])
        self.assertIn("HttpOnly", insecure[0])
        self.assertNotIn("HttpOnly", insecure[1])
        with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):
            secure = server.session_auth_service().session_cookie_headers("session-token", "csrf-token")
        self.assertIn("; Secure", secure[0])
        self.assertIn("; Secure", secure[1])
        self.assertIn("Max-Age=2592000", secure[0])

    def test_authenticated_session_throttles_last_seen_without_extending_fixed_expiry(self):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies=""):
                self.headers = {"Cookie": cookies}

        token = create_test_session(server)
        auth = server.session_auth_service()
        token_hash = auth.session_token_hash(token)
        old_seen = "2020-01-01T00:00:00+00:00"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            original = db.execute("SELECT expires_at FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()["expires_at"]
            db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (old_seen, token_hash))

        first = auth.authenticated_session(Handler(f"ic_session={token}"))
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            touched = db.execute("SELECT expires_at, last_seen FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
        second = auth.authenticated_session(Handler(f"ic_session={token}"))
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            unchanged = db.execute("SELECT expires_at, last_seen FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()

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
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", (server.time.time() - 1, auth.session_token_hash(token)))
        self.assertIsNone(auth.authenticated_session(Handler(f"ic_session={token}")))
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertIsNone(db.execute("SELECT token_hash FROM sessions WHERE token_hash=?", (auth.session_token_hash(token),)).fetchone())

    def test_expired_session_cleanup_is_bounded_and_periodic(self):
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            for index in range(http_auth.SESSION_CLEANUP_BATCH_SIZE + 1):
                db.execute(
                    "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (f"expired-{index}", f"csrf-{index}", 0, "now", "now"),
                )
            auth = server.session_auth_service()
            deleted = auth.cleanup_expired_sessions(db, server.time.time(), force=True)
            remaining = db.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
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
                results.append(server.session_auth_service().authenticated_session(Handler(cookies)))
            except Exception as exc:
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
            headers = {}

        with self.assertRaises(server.AppError) as missing:
            server.session_auth_service().require_csrf(MissingTokenHandler(), {"csrf_hash": server.session_auth_service().session_token_hash("expected")})
        self.assertEqual(missing.exception.status, 403)

        class Handler:
            headers = {"X-CSRF-Token": "foreign"}

        with self.assertRaises(server.AppError) as foreign:
            server.session_auth_service().require_csrf(Handler(), {"csrf_hash": server.session_auth_service().session_token_hash("expected")})
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

    def test_public_state_exposes_checkin_history(self):
        server.checkin_service().save(
            {"checkin_date": "2026-08-30", "motivation": 8}
        )
        state = server.public_state_service().read(local_only=True)
        self.assertEqual(state["checkins"][0]["checkin_date"], "2026-08-30")
        self.assertEqual(state["checkins"][0]["motivation"], 8)

    def test_public_states_keep_empty_usage_when_no_ai_provider_is_configured(self):
        config = replace(server.CONFIG, openai_api_key="", gemini_api_key="")

        with patch.object(server, "CONFIG", config):
            bootstrap = server.public_bootstrap_service().read()
            state = server.public_state_service().read(local_only=True)

        for result in (bootstrap, state):
            self.assertEqual(result["ai_provider"]["selected"], "")
            self.assertEqual(result["usage"]["requests"], 0)
            self.assertEqual(result["usage"]["status"], {})
            self.assertEqual(result["usage"]["rate_limits"], {})

    def test_public_state_exposes_daily_planning_context(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        server.sync_state_repository().save_snapshot({"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": [{"name": "Locker", "start_date_local": f"{today}T08:00:00"}]})
        server.checkin_service().save({"checkin_date": today, "motivation": 8})
        state = server.public_state_service().read(local_only=True)
        self.assertEqual(state["daily_planning_context"][0]["date"], today)
        self.assertEqual(state["daily_planning_context"][0]["checkin"]["motivation"], 8)

    def test_activity_pagination_has_stable_cursor_without_duplicates(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.sync_state_repository().save_snapshot({
            "synced_at": "now", "athlete": {}, "recent_wellness": [], "upcoming_calendar": [],
            "recent_activities": [
                {"id": f"activity-{index}", "name": f"Activity {index}", "type": "Ride", "start_date_local": today.isoformat()}
                for index in range(5)
            ] + [{"id": "old", "name": "Old", "type": "Ride", "start_date_local": "2000-01-01"}],
        })
        service = server.activity_read_service()
        first = service.page(limit=2, days=1, today=today)
        second = service.page(first["next_cursor"], 2, 1, today=today)
        third = service.page(second["next_cursor"], 2, 1, today=today)
        ids = [item["id"] for page in (first, second, third) for item in page["activities"]]
        self.assertEqual(ids, ["activity-4", "activity-3", "activity-2", "activity-1", "activity-0"])
        self.assertIsNone(third["next_cursor"])

    def test_chat_history_pagination_and_bounded_search_use_message_id_cursor(self):
        for index in range(5):
            server.coach_message_service().add("user", f"searchable {index}")
        page_service = server.chat_history_page_service()
        first = page_service.page(limit=2)
        second = page_service.page(cursor=first["next_cursor"], limit=2)
        page_ids = [item["id"] for item in first["messages"] + second["messages"]]
        page_contents = [item["content"] for item in first["messages"] + second["messages"]]
        self.assertEqual(set(page_contents), {"searchable 1", "searchable 2", "searchable 3", "searchable 4"})
        self.assertEqual(len(page_ids), len(set(page_ids)))
        search = page_service.page(limit=10, search="searchable 3")
        self.assertEqual([item["content"] for item in search["messages"]], ["searchable 3"])

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
            server.coach_message_service().add("user", content)

        page_service = server.chat_history_page_service()
        for search_term, expected in (
            ("percent%marker", "literal percent%marker"),
            ("underscore_marker", "literal underscore_marker"),
            (r"backslash\marker", r"literal backslash\marker"),
        ):
            with self.subTest(search_term=search_term):
                page = page_service.page(search=search_term)
                self.assertEqual([item["content"] for item in page["messages"]], [expected])

    def test_library_pagination_has_stable_type_name_id_cursor(self):
        server.workout_library_remote_reconciler().reconcile([
            {"id": f"template-{index}", "name": f"Template {index}", "type": "Ride", "description": "- 30m Z2"}
            for index in range(3)
        ])
        first = server.library_page_service().page(limit=2)
        second = server.library_page_service().page(cursor=first["next_cursor"], limit=2)
        names = [item["name"] for page in (first, second) for item in page["workouts"]]
        self.assertEqual(names, ["Template 0", "Template 1", "Template 2"])
        self.assertIsNone(second["next_cursor"])

    def test_bootstrap_is_bounded_and_excludes_history_collections(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.sync_state_repository().save_snapshot({
            "synced_at": "now", "athlete": {}, "recent_wellness": [], "upcoming_calendar": [],
            "recent_activities": [
                {"id": f"activity-{index}", "type": "Ride", "start_date_local": today.isoformat()}
                for index in range(500)
            ],
        })
        for index in range(500):
            server.coach_message_service().add("user", f"message {index}")
        bootstrap = server.public_bootstrap_service().read()
        self.assertEqual(
            list(bootstrap),
            [
                "schema_version", "state_versions", "plan_revision", "app", "skeleton",
                "messages", "messages_next_cursor", "plans", "library", "activities",
                "planned", "training_calendar", "calendar", "planning_view",
                "planning_compliance", "weather", "parallel_cycling", "profile",
                "competitions", "checkins", "local_feedback", "activity_feedback",
                "planning", "external_calendar", "daily_planning_context", "performance",
                "garmin", "diagnostic_capture", "intervals", "provider_freshness",
                "provider_states", "garmin_sync", "provider_resync", "sync", "running_jobs",
                "library_sync", "sync_settings", "calendar_display", "competition_sync",
                "performance_refresh", "morning_checkin", "coach_quick_actions",
                "ai_provider", "model", "thinking_level", "configured", "usage",
            ],
        )
        self.assertEqual(bootstrap["schema_version"], 3)
        self.assertEqual(len(bootstrap["messages"]), 100)
        self.assertEqual(bootstrap["activities"], [])
        self.assertTrue(all(bootstrap["skeleton"].values()))
        self.assertIn("plan_revision", bootstrap)
        self.assertIn("provider_states", bootstrap)
        self.assertIn("running_jobs", bootstrap)
        self.assertIn("activities", bootstrap["state_versions"])
        self.assertIn("garmin", bootstrap["state_versions"])
        self.assertLess(len(json.dumps(bootstrap, ensure_ascii=False)), 20_000)

    def test_bootstrap_never_refreshes_provider_network(self):
        with patch.object(server.provider_http_client(), "request", side_effect=AssertionError("network")), patch.object(
            server.provider_http, "external_call", side_effect=AssertionError("network")
        ):
            bootstrap = server.public_bootstrap_service().read()
        self.assertEqual(bootstrap["schema_version"], 3)
        self.assertIn(bootstrap["provider_states"]["intervals"]["status"], {"not_configured", "loading", "ready", "stale", "degraded", "error"})

    def test_state_events_report_missed_retention_and_redact_content(self):
        runtime_events.STATE_EVENT_BUFFER.clear()
        for index in range(501):
            runtime_events.STATE_EVENT_BUFFER.publish("job", {"job_id": f"job-{index}", "status": "running", "progress": {"completed": index, "total": 501}})
        gap = runtime_events.STATE_EVENT_BUFFER.since(0)
        self.assertTrue(gap["gap"])
        self.assertEqual(gap["events"], [])
        current = runtime_events.STATE_EVENT_BUFFER.since(gap["latest_event_id"] - 1)
        self.assertFalse(current["gap"])
        self.assertEqual(len(current["events"]), 1)
        self.assertNotIn("athlete content", json.dumps(current))

    def test_state_events_validate_cursor_and_publish_job_progress(self):
        with self.assertRaises(server.AppError) as raised:
            runtime_events.STATE_EVENT_BUFFER.since("not-a-number")
        self.assertEqual(raised.exception.reason, "invalid_event_cursor")
        event = runtime_events.STATE_EVENT_BUFFER.publish("job", {"job_id": "job-1", "status": "completed", "progress": {"completed": 1, "total": 1}})
        self.assertEqual(runtime_events.STATE_EVENT_BUFFER.since(event["event_id"] - 1)["events"][0]["data"]["progress"]["completed"], 1)

    def test_state_event_batch_sends_events_and_resets_for_gaps(self):
        transport = StateEventTransport(runtime_events.STATE_EVENT_BUFFER)
        sent = []
        since, gap = transport.send_batch({
            "gap": False,
            "latest_event_id": 5,
            "events": [
                {"event_id": 4, "event": "provider", "data": {"status": "running"}},
                {"event_id": 5, "event": "provider", "data": {"status": "completed"}},
            ],
        }, 3, lambda event, payload, event_id=None: sent.append((event, payload, event_id)))
        self.assertEqual((since, gap), (5, False))
        self.assertEqual(sent[-1], ("provider", {"status": "completed"}, 5))
        since, gap = transport.send_batch(
            {"gap": True, "latest_event_id": 9, "events": []},
            since,
            lambda event, payload, event_id=None: sent.append((event, payload, event_id)),
        )
        self.assertEqual((since, gap), (9, True))
        self.assertEqual(sent[-1], ("reset", {"reason": "gap", "latest_event_id": 9}, 9))

    def test_state_events_route_requires_auth_before_starting_transport(self):
        handler = object.__new__(server.request_handler_class())
        handler.path = "/api/state/events?since=0"
        handler.connection = Mock()
        handler.send_sse_headers = Mock()
        handler.send_sse_event = Mock()
        auth = Mock()
        transport = Mock()
        routes = StateEventsGetRoutes(lambda: auth, transport)

        with patch.object(transport, "handle") as handle:
            self.assertTrue(routes.handle(handler, "/api/state/events"))
            auth.require_auth.assert_called_once_with(handler)
            handle.assert_called_once_with(
                handler.path,
                send_headers=handler.send_sse_headers,
                send_event=handler.send_sse_event,
                set_connection_timeout=handler.connection.settimeout,
            )

        denied = server.AppError(401, "unauthorized")
        auth.require_auth.side_effect = denied
        auth.require_auth.reset_mock()
        handler.connection.settimeout.reset_mock()
        with patch.object(transport, "handle") as handle:
            with self.assertRaises(server.AppError) as caught:
                routes.handle(handler, "/api/state/events")
            self.assertIs(caught.exception, denied)
            auth.require_auth.assert_called_once_with(handler)
            handle.assert_not_called()
            handler.connection.settimeout.assert_not_called()
            handler.send_sse_headers.assert_not_called()
            handler.send_sse_event.assert_not_called()

        auth.require_auth.side_effect = None
        auth.require_auth.reset_mock()
        transport.handle.reset_mock()
        self.assertFalse(routes.handle(handler, "/api/state/events/extra"))
        auth.require_auth.assert_not_called()
        transport.handle.assert_not_called()
        handler.connection.settimeout.assert_not_called()

        second_auth = Mock()
        auth_factory = Mock(side_effect=[auth, second_auth])
        routes = StateEventsGetRoutes(auth_factory, transport)
        routes.handle(handler, "/api/state/events")
        routes.handle(handler, "/api/state/events")
        self.assertEqual(auth_factory.call_count, 2)
        auth.require_auth.assert_called_once_with(handler)
        second_auth.require_auth.assert_called_once_with(handler)

    def test_http_response_helpers_are_dependency_light_and_preserve_headers(self):
        from backend.http_api import responses

        source = Path(responses.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)
        self.assertEqual(responses.json_bytes({"text": "ä"}), b'{"text": "\xc3\xa4"}')
        self.assertEqual(
            list(responses.header_items({"Set-Cookie": ["one", "two"], "X-Test": "value"})),
            [("Set-Cookie", "one"), ("Set-Cookie", "two"), ("X-Test", "value")],
        )
        self.assertEqual(
            responses.response_headers("application/json", 12),
            (("Content-Type", "application/json"), ("Content-Length", "12"), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY")),
        )
        self.assertEqual(
            responses.session_cookies("session", "csrf", "token", "csrf-token", ttl_seconds=60, secure=True),
            ["session=token; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=60", "csrf=csrf-token; Path=/; SameSite=Strict; Secure; Max-Age=60"],
        )
        self.assertEqual(
            responses.session_cookies("session", "csrf", "token", "csrf-token", ttl_seconds=60, clear=True),
            ["session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0", "csrf=; Path=/; SameSite=Strict; Max-Age=0"],
        )

    def test_http_request_helpers_are_dependency_light_and_preserve_limits(self):
        from backend.http_api import requests

        source = Path(requests.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)
        headers = {"Content-Length": "7"}
        self.assertEqual(requests.read_body(headers, BytesIO(b"payload").read, 10, error=server.AppError), b"payload")
        self.assertEqual(
            requests.read_json(
                {"Content-Type": "application/json; charset=utf-8", "Content-Length": "12"},
                BytesIO(b'{"ok": true}').read,
                100,
                error=server.AppError,
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
                error=server.AppError,
            ),
            b"audio",
        )
        with self.assertRaises(server.AppError) as oversized:
            requests.read_body({"Content-Length": "11"}, BytesIO(b"x" * 11).read, 10, error=server.AppError)
        self.assertEqual(oversized.exception.status, 413)
        with self.assertRaises(server.AppError) as malformed:
            requests.read_json(
                {"Content-Type": "application/json", "Content-Length": "9"},
                BytesIO(b"not-json!").read,
                100,
                error=server.AppError,
            )
        self.assertEqual(malformed.exception.status, 400)
        with self.assertRaises(server.AppError) as wrong_type:
            requests.read_json(
                {"Content-Type": "text/plain", "Content-Length": "7"},
                BytesIO(b'{"ok":1}').read,
                100,
                error=server.AppError,
            )
        self.assertEqual(wrong_type.exception.status, 415)
        with self.assertRaises(server.AppError) as non_object:
            requests.read_json(
                {"Content-Type": "application/json", "Content-Length": "2"},
                BytesIO(b"[]").read,
                100,
                error=server.AppError,
            )
        self.assertEqual(non_object.exception.status, 400)
        with self.assertRaises(server.AppError) as incomplete:
            requests.read_audio_body(
                {"Content-Type": "audio/webm", "Content-Length": "5"},
                BytesIO(b"aud").read,
                allowed_types={"audio/webm": ".webm"},
                normalize_type=lambda value: value.split(";", 1)[0],
                max_bytes=10,
                error=server.AppError,
            )
        self.assertEqual(incomplete.exception.status, 400)

    def test_public_state_exposes_provider_calendar_window(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.sync_state_repository().save_snapshot({
            "synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": [],
            "provider_sync": {"calendar_window": {"start": (today - timedelta(days=10)).isoformat(), "end": (today + timedelta(days=20)).isoformat()}},
        })
        state = server.public_state_service().read(local_only=True)
        self.assertEqual(state["planning_view"]["provider_window"]["end"], (today + timedelta(days=20)).isoformat())
        self.assertNotIn("public_calendar", state)

    def test_intervals_collection_pagination_is_bounded_and_reported(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key"))
        first_page = [{"id": f"activity-{index}"} for index in range(500)]
        second_page = [{"id": "activity-500"}]
        with patch.object(client._api, "get", side_effect=[first_page, second_page]) as get:
            rows = client.get_paged_collection("/athlete/0/activities", {"oldest": "2026-01-01"}, "activities")
        self.assertEqual(len(rows), 501)
        self.assertEqual(client.pagination["activities"], {"pages": 2, "records": 501, "complete": True})
        self.assertEqual(get.call_args_list[1].args[1]["offset"], 500)

    def test_body_battery_only_error_does_not_degrade_garmin_public_state(self):
        server.key_value_service().set("last_garmin_error", json.dumps([
            {"source": "body_battery", "message": "optional request unavailable"},
        ]))

        self.assertIsNone(server.garmin_projection_service().public_state()["last_error"])

    def test_provider_authentication_errors_do_not_use_the_session_status(self):
        provider_error = server.AppError(401, "Gemini-SchlÃ¼ssel ungÃ¼ltig.", reason="authentication_or_permission")
        self.assertEqual(server.public_app_error_status(provider_error), 502)
        self.assertEqual(server.public_app_error_status(server.AppError(401, "Anmeldung erforderlich.")), 401)

    def test_http_json_cancels_while_waiting_for_provider_headers(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        cancelled = threading.Event()
        outcome = {}

        class Response:
            status = 200
            headers = {}

            def read(self, *args):
                return b"{}"

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def blocked_urlopen(*args, **kwargs):
            started.set()
            release.wait(2)
            finished.set()
            return Response()

        def send_request():
            try:
                server.provider_http_client().request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent", {}, service="gemini", cancel_event=cancelled)
            except server.AppError as exc:
                outcome["error"] = exc

        with patch.object(server.provider_http_client(), "opener", side_effect=blocked_urlopen):
            caller = threading.Thread(target=send_request)
            caller.start()
            self.assertTrue(started.wait(1))
            cancelled.set()
            caller.join(1)
            release.set()
            self.assertTrue(finished.wait(1))

        self.assertFalse(caller.is_alive())
        self.assertEqual(outcome["error"].status, 499)

    def test_http_json_clears_provider_response_handle_after_read(self):
        cancel_event = threading.Event()
        class Response:
            status = 200
            headers = {}

            def read(self, *_args):
                return b"{}"

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        response = Response()
        with patch.object(server.provider_http_client(), "opener", return_value=response):
            self.assertEqual(
                server.provider_http_client().request(
                    "GET", "https://intervals.icu/api/v1/athlete/0", service="intervals", cancel_event=cancel_event
                ),
                {},
            )
        self.assertIsNone(getattr(cancel_event, "_provider_response", None))

    def test_http_json_rechecks_cancellation_after_provider_response(self):
        cancel_event = threading.Event()

        class Response:
            status = 200
            headers = {}

            def read(self, *_args):
                raise AssertionError("cancelled response must not be read")

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        response = Response()
        def return_cancelled_response(*_args, **_kwargs):
            cancel_event.set()
            return response

        with patch.object(server.provider_http_client(), "opener", side_effect=return_cancelled_response):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request(
                    "GET", "https://intervals.icu/api/v1/athlete/0", service="intervals", cancel_event=cancel_event
                )
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertIsNone(getattr(cancel_event, "_provider_response", None))

    def test_http_json_preserves_empty_body_and_oversized_response_contracts(self):
        class EmptyResponse:
            status = 204
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b""

        with patch.object(server.provider_http_client(), "opener", return_value=EmptyResponse()):
            self.assertIsNone(server.provider_http_client().request("DELETE", "https://intervals.icu/api/v1/athlete/0", service="intervals"))

        class OversizedResponse(EmptyResponse):
            status = 200

            def read(self, *_args):
                return b"1234"

        with (
            patch.object(server.provider_http_client(), "max_response_bytes", 3),
            patch.object(server.provider_http_client(), "opener", return_value=OversizedResponse()),
            self.assertRaises(server.AppError) as raised,
        ):
            server.provider_http_client().request("GET", "https://intervals.icu/api/v1/athlete/0", service="intervals")
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.message, "Die Antwort des externen Dienstes ist zu groß.")

    def test_transcribe_audio_sends_bounded_multipart_request(self):
        captured = {}

        def fake_http_json(method, url, payload=None, headers=None, timeout=45, service=None, raw_body=None, content_type=None):
            captured.update({
                "method": method, "url": url, "payload": payload, "headers": headers,
                "timeout": timeout, "service": service, "raw_body": raw_body, "content_type": content_type,
            })
            return {"text": "Wie soll ich morgen trainieren?"}

        audio = b"fake-webm-audio"
        with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(
            server.provider_http_client(), "request", side_effect=fake_http_json
        ):
            result = _transcribe_via_http_route(audio, "audio/webm;codecs=opus")

        self.assertEqual(result, {"transcript": "Wie soll ich morgen trainieren?"})
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "https://foundry.example.invalid/openai/v1/audio/transcriptions")
        self.assertEqual(captured["service"], "openai")
        self.assertEqual(captured["timeout"], 90)
        self.assertIsNone(captured["payload"])
        self.assertIn("multipart/form-data; boundary=", captured["content_type"])
        self.assertIn(b'name="model"', captured["raw_body"])
        self.assertIn(b"gpt-transcribe", captured["raw_body"])
        self.assertIn(audio, captured["raw_body"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")

    def test_transcribe_audio_rejects_unknown_format_and_oversized_audio(self):
        config = replace(server.CONFIG, openai_api_key="test-key")
        with patch.object(server, "CONFIG", config):
            with self.assertRaises(server.AppError) as unsupported:
                _transcribe_via_http_route(b"audio", "audio/flac")
            with self.assertRaises(server.AppError) as oversized:
                _transcribe_via_http_route(b"x" * (server.MAX_AUDIO_BODY_BYTES + 1), "audio/webm")
        self.assertEqual(unsupported.exception.status, 415)
        self.assertEqual(oversized.exception.status, 413)

    def test_complete_plan_replace_can_create_more_sessions_and_archive_old_ones(self):
        old = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Old", "description": "- 30m 60% easy",
        })
        state = server.structured_training_state_service().read()
        intent = {
            "intent": "local_action", "operation": "replace_training_plan", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
            "follow_up_operations": [],
        }
        result = server.coach_tool_dispatch_service().execute(
            "replace_training_plan",
            {
                "expected_revision": state["planning_revision"],
                "payload": {"plan_name": "Replacement", "goal": "Base", "workouts": [
                    {"date": (date.today() + timedelta(days=2)).isoformat(), "sport": "Ride", "name": "New 1", "description": "- 40m 60% easy", "duration_minutes": 40, "target": "AUTO", "rationale": "Base"},
                    {"date": (date.today() + timedelta(days=3)).isoformat(), "sport": "Run", "name": "New 2", "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO", "rationale": "Base"},
                ]},
            },
            intent=intent, conversation_id="conversation-replace", client_turn_id="turn-replace",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["status"], "replaced")
        self.assertEqual(result["archived_count"], 1)
        self.assertEqual(result["created_count"], 2)
        self.assertEqual({item["name"] for item in server.planned_unit_service().list()}, {"New 1", "New 2"})
        archived = next(item for item in server.planned_unit_service().list(20, include_archived=True) if item["id"] == old["id"])
        self.assertTrue(archived["archived"])
        self.assertTrue(archived["local_deleted"])

    def test_openai_background_request_routes_checkpoint_and_cancellation_to_provider_client(self):
        checkpoints = []
        checkpoint = checkpoints.append
        expected = {"id": "resp_background_1", "status": "completed", "output_text": "fertig", "usage": {}}
        payload = {"model": "gpt-6-luna", "input": "fake"}
        with patch.object(
            server.openai_provider.OpenAIResponsesClient, "background", return_value=expected
        ) as background:
            result = server.coach_response_transport().background_request(
                payload, on_response_id=checkpoint
            )

        background.assert_called_once_with(
            payload,
            response_id=None,
            on_response_id=checkpoint,
            cancel_event=None,
        )
        self.assertEqual(result["status"], "completed")

    def test_background_coach_job_is_persisted_and_session_scoped(self):
        job = server.coach_job_submission_service().enqueue(
            "Erstelle einen Trainingsplan für die nächsten 2 Wochen.",
            "turn-background-persisted",
            "csrf-background-owner",
            operation_id="operation-background-persisted",
        )
        self.assertEqual(job["status"], "queued")
        status = server.coach_job_submission_service().stream_status("csrf-background-owner")
        self.assertEqual(status["mode"], "background")
        self.assertEqual(status["operation_id"], "operation-background-persisted")
        self.assertEqual(
            server.coach_job_submission_service().stream_status("csrf-other"),
            {"status": "idle", "operation_id": None},
        )
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            command = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-background-persisted'"
            ).fetchone()
            user_message = db.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(command["status"], "queued")
        self.assertNotIn("csrf-background-owner", command["receipt"])
        self.assertEqual(user_message["role"], "user")
        self.assertIn("2 Wochen", user_message["content"])

    def test_background_submission_atomically_allows_only_one_active_turn_per_session(self):
        service = server.coach_job_submission_service()
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
                results.append(service.enqueue(
                    "Erstelle eine längere Planung", client_turn_id,
                    "csrf-background-concurrent-session", operation_id=f"operation-{client_turn_id}",
                ))
            except server.AppError as error:
                errors.append(error)

        registry = server.coach_streams.CHAT_STREAM_REGISTRY
        with (
            patch.object(service, "active", side_effect=synchronized_active),
            patch.object(server.runtime_events.STATE_EVENT_BUFFER, "publish"),
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
        self.assertIsInstance(errors[0], server.AppError)
        self.assertEqual(errors[0].reason, "chat_already_running")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
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
        server.planned_unit_service().create({"date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Ride", "name": "Intervalle", "description": "- 30m Z2", "duration_minutes": 30})
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [{"name": "Morgenlauf"}], "recent_wellness": [], "upcoming_calendar": []}
        server.sync_state_repository().save_snapshot(snapshot)
        state = server.public_state_service().read()
        self.assertEqual(state["app"]["name"], "Intervals Coach")
        self.assertEqual(state["app"]["version"], server.APP_VERSION)
        self.assertEqual(state["activities"][0]["name"], "Morgenlauf")
        self.assertEqual(state["planned"][0]["name"], "Intervalle")
        self.assertEqual(state["calendar_display"], {"past_weeks": 1, "future_weeks": 4})

    def test_json_response_ignores_client_disconnect(self):
        handler = object.__new__(server.request_handler_class())
        handler.request_id = "request-1"
        handler.command = "GET"
        handler.path = "/api/state"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=BrokenPipeError())
        handler.wfile = Mock()
        handler.log_client_disconnect = Mock()

        server.request_handler_class().send_json(handler, 200, {"status": "ok"})

        handler.log_client_disconnect.assert_called_once_with()
        handler.wfile.write.assert_not_called()

    def test_response_transport_uses_redacted_application_logger(self):
        self.assertIs(response_transport.LOGGER, server.LOGGER)

    def test_json_response_disconnect_logs_response_metadata(self):
        handler = object.__new__(server.request_handler_class())
        handler.request_id = "request-2"
        handler.command = "GET"
        handler.path = "/api/activities"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=ConnectionResetError())
        handler.wfile = Mock()

        with patch.object(server.LOGGER, "info") as logger:
            server.request_handler_class().send_json(handler, 200, {"activities": []})

        context = logger.call_args.kwargs["extra"]["context"]
        self.assertEqual(context["method"], "GET")
        self.assertEqual(context["path"], "/api/activities")
        self.assertEqual(context["request_id"], "request-2")
        self.assertEqual(context["response_status"], 200)
        self.assertEqual(context["response_bytes"], len(responses.json_bytes({"activities": []})))
        self.assertEqual(context["error_type"], "ConnectionResetError")
        self.assertGreaterEqual(context["response_duration_ms"], 0)

    def test_http_error_response_body_is_closed_after_reading(self):
        response_body = BytesIO(b'{"error":{"message":"temporary failure"}}')
        upstream_error = HTTPError(
            "https://intervals.icu/api/v1/athlete/0",
            503,
            "Service Unavailable",
            {},
            response_body,
        )
        with patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError):
                server.provider_http_client().request("GET", "https://intervals.icu/api/v1/athlete/0", service="intervals")
        self.assertTrue(response_body.closed)

    def test_intervals_public_state_reports_sync_health(self):
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config):
            server.key_value_service().set("last_library_sync_at", "2026-08-31T08:00:00+00:00")
            state = server.public_state_service().read(local_only=True)["intervals"]
        self.assertEqual(state["state"], "connected")
        self.assertIsNone(state["last_sync_at"])
        self.assertEqual(state["library_sync"]["last_sync_at"], "2026-08-31T08:00:00+00:00")
        self.assertIsNone(state["last_error"])

    def test_intervals_public_state_reports_library_error(self):
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config):
            server.key_value_service().set("last_library_sync_error", "Intervals.icu weist die Anfrage zurück (422): Invalid workout type")
            state = server.public_state_service().read(local_only=True)["intervals"]
        self.assertEqual(state["state"], "error")
        self.assertIn("422", state["last_error"])

    def test_readiness_is_safe_and_separate_from_liveness(self):
        with tempfile.TemporaryDirectory() as data_dir:
            readiness = ReadinessService(
                server.database_manager, server.DB_LOCK, Path(data_dir),
                runtime_maintenance.MAINTENANCE_GATE,
            ).state()
            self.assertEqual([], list(Path(data_dir).glob(".readiness-*.probe")))
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["ready"])
        self.assertEqual(set(readiness["checks"]), {"database", "schema", "data_directory", "maintenance"})
        self.assertNotIn("path", json.dumps(readiness).casefold())
        self.assertNotIn("athlete", json.dumps(readiness).casefold())
        self.assertNotIn("password", json.dumps(readiness).casefold())

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
        handler = object.__new__(server.request_handler_class())
        handler.send_json = Mock()

        original_manager = server.database_manager()
        switched_manager = Mock()
        seen_managers = []

        def projected_state(service):
            seen_managers.append(service._manager_factory())
            return ready if len(seen_managers) == 1 else not_ready

        with patch.object(server, "database_manager", side_effect=[original_manager, switched_manager]), \
                patch.object(ReadinessService, "state", autospec=True, side_effect=projected_state):
            self.assertTrue(server.PUBLIC_GET_ROUTES.handle(handler, "/api/readiness"))
            self.assertTrue(server.PUBLIC_GET_ROUTES.handle(handler, "/api/readiness"))

        self.assertEqual(seen_managers, [original_manager, switched_manager])
        self.assertEqual(
            handler.send_json.call_args_list,
            [call(200, ready), call(503, not_ready)],
        )

    def test_readiness_handler_returns_503_when_manager_composition_fails(self):
        handler = object.__new__(server.request_handler_class())
        handler.send_json = Mock()
        with tempfile.TemporaryDirectory() as data_dir, \
                patch.object(server, "DATA_DIR", Path(data_dir)), \
                patch.object(server, "database_manager", side_effect=OSError("mount unavailable")):
            self.assertTrue(server.PUBLIC_GET_ROUTES.handle(handler, "/api/readiness"))
        status, payload = handler.send_json.call_args.args
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["checks"]["database"])
        self.assertFalse(payload["checks"]["schema"])
        self.assertNotIn("mount unavailable", json.dumps(payload))

    def test_readiness_fails_when_data_directory_is_read_only(self):
        with tempfile.TemporaryDirectory() as data_dir, patch.object(
            readiness_module.tempfile, "NamedTemporaryFile",
            side_effect=OSError("read-only"),
        ):
            readiness = ReadinessService(
                server.database_manager, server.DB_LOCK, Path(data_dir),
                runtime_maintenance.MAINTENANCE_GATE,
            ).state()
        self.assertEqual(readiness["status"], "not_ready")
        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["checks"]["data_directory"])

    def test_readiness_cleans_up_probe_after_write_failure(self):
        with tempfile.TemporaryDirectory() as data_dir:
            named_temporary_file = readiness_module.tempfile.NamedTemporaryFile

            def broken_probe(**kwargs):
                handle = named_temporary_file(**kwargs)

                class BrokenWriter:
                    name = handle.name

                    def __enter__(self):
                        handle.__enter__()
                        return self

                    def __exit__(self, *args):
                        return handle.__exit__(*args)

                    def write(self, _content):
                        raise OSError("probe write failed")

                return BrokenWriter()

            with patch.object(
                readiness_module.tempfile, "NamedTemporaryFile", side_effect=broken_probe
            ):
                readiness = ReadinessService(
                    server.database_manager, server.DB_LOCK, Path(data_dir),
                    runtime_maintenance.MAINTENANCE_GATE,
                ).state()
            self.assertFalse(readiness["checks"]["data_directory"])
            self.assertEqual([], list(Path(data_dir).glob(".readiness-*.probe")))

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
        with patch("backend.http_api.rate_limit.time.monotonic", side_effect=(1000.0, 1002.0, 1002.0)):
            self.assertEqual(limiter.allow("login:one", 1, 10), (True, 10))
            self.assertEqual(limiter.allow("login:one", 1, 10), (False, 8))
            self.assertEqual(limiter.allow("login:two", 1, 10), (True, 10))

    def test_api_auth_uses_rate_limiter_and_preserves_retry_response(self):
        handler = Mock(client_address=("203.0.113.7", 0))
        auth = server.session_auth_service()
        with patch.object(server.app_config, "security_configuration_error", return_value=None), \
                patch.object(auth, "authenticated_session", return_value={"csrf_hash": "unused"}), \
                patch.object(RateLimiter, "allow", autospec=True, return_value=(False, 17)) as rate_limit, \
                self.assertRaises(server.AppError) as raised:
            auth.require_auth(handler)
        self.assertEqual(raised.exception.status, 429)
        self.assertIn("17 Sekunden", raised.exception.message)
        rate_limit.assert_called_once_with(server.RATE_LIMITER, "api:203.0.113.7", 180, 60)

    def test_openai_rate_limit_headers_are_exposed_without_local_limits(self):
        class FakeResponse:
            status = 200
            headers = {
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

        with patch.object(server.provider_http_client(), "opener", return_value=FakeResponse()):
            server.provider_http_client().request("POST", "https://api.openai.com/v1/responses", payload={}, service="openai")
        summary = server.provider_state_service().summary("openai")
        self.assertNotIn("request_limit", summary)
        self.assertNotIn("token_limit", summary)
        self.assertEqual(summary["rate_limits"]["remaining_requests"], "19")
        self.assertEqual(summary["rate_limits"]["remaining_tokens"], "12000")
        self.assertEqual(summary["status"]["state"], "ok")

    def test_responses_request_routes_openai_to_provider_client(self):
        payload = {"model": "gpt-6-luna"}
        with patch.object(
            server.openai_provider.OpenAIResponsesClient,
            "responses",
            return_value={"output_text": "ok"},
        ) as responses:
            result = server.coach_response_transport().request(payload)
        self.assertEqual(result["output_text"], "ok")
        responses.assert_called_once_with(payload)

    def test_responses_stream_request_routes_openai_to_provider_client(self):
        payload = {"model": "gpt-6-luna"}
        cancel_event = threading.Event()
        on_delta = Mock()
        on_response_id = Mock()

        with patch.object(
            server.openai_provider.OpenAIStreamClient,
            "stream",
            return_value={"status": "completed"},
        ) as stream:
            result = server.coach_response_transport().stream_request(payload, on_delta, cancel_event, on_response_id)

        self.assertEqual(result["status"], "completed")
        stream.assert_called_once_with(
            payload,
            on_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )

    def test_chat_stream_registration_rejects_duplicate_stream_and_wrong_operation_id(self):
        session_key = "session-stream-test"
        operation_id, cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(session_key)
        try:
            with self.assertRaises(server.AppError) as duplicate:
                coach_streams.CHAT_STREAM_REGISTRY.register(session_key)
            self.assertEqual(duplicate.exception.reason, "chat_already_running")
            with self.assertRaises(server.AppError) as raised:
                server.coach_cancellation_service().cancel(session_key, "other-operation")
            self.assertEqual(raised.exception.status, 409)
            result = server.coach_cancellation_service().cancel(session_key, operation_id)
            self.assertEqual(result["status"], "cancelling")
            self.assertTrue(cancel_event.is_set())
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(session_key, operation_id)

    def test_chat_stream_status_is_scoped_to_the_session(self):
        session_key = "session-stream-status-test"
        service = server.coach_job_submission_service()
        self.assertEqual(service.stream_status(session_key), {"status": "idle", "operation_id": None})
        operation_id, cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(session_key)
        try:
            self.assertEqual(service.stream_status(session_key), {"status": "running", "operation_id": operation_id})
            self.assertEqual(service.stream_status("other-session"), {"status": "idle", "operation_id": None})
            self.assertFalse(cancel_event.is_set())
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(session_key, operation_id)

    def test_chat_stream_registry_isolates_sessions_and_preserves_event_order(self):
        registry = coach_streams.ChatStreamRegistry()
        first_operation, _ = registry.register("session-one")
        second_operation, _ = registry.register("session-two")
        try:
            self.assertNotEqual(first_operation, second_operation)
            self.assertIsNone(registry.events("session-two", first_operation))
            self.assertTrue(registry.publish(first_operation, "delta", {"text": "one"}))
            self.assertTrue(registry.publish(first_operation, "completed", {"status": "done"}))
            first_events = registry.events("session-one", first_operation)
            self.assertEqual(first_events.get_nowait(), ("delta", {"text": "one"}))
            self.assertEqual(first_events.get_nowait(), ("completed", {"status": "done"}))
            self.assertFalse(registry.publish("unknown-operation", "error", {}))
        finally:
            registry.unregister("session-one", first_operation)
            registry.unregister("session-two", second_operation)
        self.assertFalse(registry.publish(first_operation, "delta", {"text": "after detach"}))

    def test_disconnected_chat_stream_continues_and_does_not_cancel_provider_work(self):
        session_key = "session-stream-disconnect-test"
        operation_id = "operation-disconnect-test"
        cancel_event = threading.Event()
        handler_class = server.request_handler_class()
        handler = handler_class.__new__(handler_class)
        handler.read_json = Mock(return_value={"message": "Bleibt bestehen", "client_turn_id": "turn-disconnect-test"})
        handler.connection = Mock()
        handler.send_sse_headers = Mock()
        handler.send_sse_event = Mock(side_effect=[None, ClientDisconnected()])
        events = queue.Queue()
        events.put(("delta", {"text": "Antwort bleibt gespeichert"}))
        events.put(("completed", {"message": {"id": 2}}))

        registry = coach_streams.CHAT_STREAM_REGISTRY
        with patch.object(registry, "register", return_value=(operation_id, cancel_event)), \
                patch.object(registry, "unregister") as unregister, \
                patch.object(registry, "events", return_value=events):
            server.CHAT_STREAM_TRANSPORT.handle(handler, {"csrf_hash": session_key})

        with server.database_manager().unit_of_work() as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM coach_commands WHERE client_turn_id='turn-disconnect-test' AND status='queued'").fetchone())
        self.assertFalse(cancel_event.is_set())
        unregister.assert_called_once_with(session_key, operation_id)

    def test_durable_chat_stream_relays_worker_deltas_and_completion(self):
        session_key = "session-background-stream-test"
        operation_id = "operation-background-stream-test"
        cancel_event = threading.Event()
        handler_class = server.request_handler_class()
        handler = handler_class.__new__(handler_class)
        handler.read_json = Mock(return_value={
            "message": "Erstelle einen Trainingsplan für die nächsten 2 Wochen.",
            "client_turn_id": "turn-background-stream-test",
        })
        handler.connection = Mock()
        handler.send_sse_headers = Mock()
        handler.send_sse_event = Mock()
        events = queue.Queue()
        events.put(("delta", {"text": "Dein Plan "}))
        events.put(("delta", {"text": "ist fertig."}))
        events.put(("completed", {"status": "completed", "message": {"id": 2, "content": "Dein Plan ist fertig."}}))

        registry = coach_streams.CHAT_STREAM_REGISTRY
        with patch.object(registry, "register", return_value=(operation_id, cancel_event)), patch.object(
            registry, "unregister"
        ) as unregister, patch.object(registry, "events", return_value=events):
            server.CHAT_STREAM_TRANSPORT.handle(handler, {"csrf_hash": session_key})

        events = [call.args[0] for call in handler.send_sse_event.call_args_list]
        self.assertEqual(events, ["started", "delta", "delta", "completed"])
        handler.send_sse_headers.assert_called_once_with(persistent=False)
        self.assertTrue(handler.close_connection)
        unregister.assert_called_once_with(session_key, operation_id)

    def test_chat_stream_cancel_closes_the_active_provider_response(self):
        session_key = "session-stream-close-test"
        operation_id, cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(session_key)
        response = Mock()
        cancel_event._openai_response = response
        try:
            result = server.coach_cancellation_service().cancel(session_key, operation_id)
            self.assertEqual(result["status"], "cancelling")
            response.close.assert_called_once_with()
            self.assertTrue(cancel_event.is_set())
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(session_key, operation_id)

    def test_chat_queue_is_bounded_instead_of_waiting_indefinitely(self):
        gate = server.COACH_CONVERSATION_GATE
        acquired = [gate._queue.acquire(blocking=False) for _ in range(3)]
        self.assertTrue(all(acquired))
        try:
            @gate.wrap
            def queued_operation():
                return "completed"

            with self.assertRaises(server.AppError) as raised:
                queued_operation()
            self.assertEqual(raised.exception.reason, "chat_queue_full")
        finally:
            for was_acquired in acquired:
                if was_acquired:
                    gate._queue.release()

    def test_public_state_and_usage_workers_do_not_deadlock(self):
        # Reproduce the AB/BA ordering: a state request owns DB_LOCK while a
        # worker starts reading/updating usage, then the request reads usage.
        # Bound the worker's lock wait so a regression fails without leaving
        # either thread or the test database permanently locked.
        request_thread = threading.get_ident()

        class ObservedDatabaseLock:
            def __init__(self):
                self.lock = threading.RLock()
                self.worker_waiting = threading.Event()

            def __enter__(self):
                if threading.get_ident() != request_thread:
                    self.worker_waiting.set()
                if not self.lock.acquire(timeout=3):
                    raise TimeoutError("State request and usage worker deadlocked")
                return self

            def __exit__(self, *args):
                self.lock.release()

        for state_reader in (
            lambda: server.public_bootstrap_service().read(),
            lambda: server.public_state_service().read(),
        ):
            for update in (False, True):
                with self.subTest(state=state_reader.__name__, update=update):
                    database_lock = ObservedDatabaseLock()
                    errors = []

                    with patch.object(server, "DB_LOCK", database_lock), patch.object(
                        provider_http, "urlopen", side_effect=AssertionError("State must stay local")
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
                            except Exception as exc:
                                errors.append(exc)

                        thread = threading.Thread(target=worker)
                        try:
                            with server.DB_LOCK, server.database_manager().unit_of_work():
                                thread.start()
                                self.assertTrue(database_lock.worker_waiting.wait(timeout=3))
                                state = state_reader()
                                self.assertIn("usage", state)
                        finally:
                            thread.join(timeout=5)
                        self.assertFalse(thread.is_alive())
                        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
