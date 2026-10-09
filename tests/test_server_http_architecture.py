from __future__ import annotations

import ast
import unittest

try:
    from .architecture_analysis import (
        parse_python as _parse,
    )
    from .architecture_analysis import (
        request_handler_definition as _request_handler_definition,
    )
    from .architecture_registry import (
        BACKEND_ROOT,
        SERVER_PATH,
    )
except ImportError:
    from architecture_analysis import (
        parse_python as _parse,
    )
    from architecture_analysis import (
        request_handler_definition as _request_handler_definition,
    )
    from architecture_registry import (
        BACKEND_ROOT,
        SERVER_PATH,
    )


class ServerHttpArchitectureTests(unittest.TestCase):
    def _assert_get_route_owned(
        self,
        old_method: str,
        route_name: str,
        *,
        method_must_be_absent: bool = True,
        forbidden_paths: tuple[str, ...] = (),
    ) -> ast.Module:
        assembly_tree = _parse(BACKEND_ROOT / "http_api" / "assembly.py")
        request_handler = _request_handler_definition()
        methods = {
            node.name
            for node in request_handler.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        get_handler = next(
            node
            for node in request_handler.body
            if isinstance(node, ast.FunctionDef) and node.name == "do_GET"
        )
        init = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HttpApiAssembly"
        )
        init_method = next(
            node
            for node in init.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        route_attr = route_name.lower()
        assignment = next(
            node
            for node in ast.walk(init_method)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == route_attr
                for target in node.targets
            )
        )
        dispatcher = next(
            node
            for node in ast.walk(init_method)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "route_dispatcher"
                for target in node.targets
            )
        )
        route_dispatches = [
            node
            for node in ast.walk(dispatcher.value)
            if isinstance(node, ast.Attribute) and node.attr == route_attr
        ]
        if method_must_be_absent:
            self.assertNotIn(old_method, methods)
        self.assertEqual(len(route_dispatches), 1)
        self.assertIn(
            "dependencies.route_dispatcher.handle_get", ast.unparse(get_handler)
        )
        self.assertIsInstance(assignment.value, ast.Call)
        if forbidden_paths:
            handler_paths = {
                node.value
                for node in ast.walk(get_handler)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            self.assertTrue(set(forbidden_paths).isdisjoint(handler_paths))
        return assembly_tree

    def _assert_route_factories(
        self, assembly_tree: ast.Module, route_name: str, expected_names: list[str]
    ) -> None:
        init = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HttpApiAssembly"
        )
        init_method = next(
            node
            for node in init.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        route_attr = route_name.lower()
        assignment = next(
            node
            for node in ast.walk(init_method)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == route_attr
                for target in node.targets
            )
        )
        self.assertEqual(len(assignment.value.args), len(expected_names))
        expected_factory = {
            "COACH_GET_ROUTES": "CoachGetRoutes",
            "PUBLIC_GET_ROUTES": "PublicGetRoutes",
            "PLANNING_GET_ROUTES": "PlanningGetRoutes",
            "ATHLETE_GET_ROUTES": "AthleteGetRoutes",
            "SYNC_GET_ROUTES": "SyncGetRoutes",
            "STATE_EVENTS_GET_ROUTES": "StateEventsGetRoutes",
            "HISTORY_GET_ROUTES": "HistoryGetRoutes",
            "DIAGNOSTICS_GET_ROUTES": "DiagnosticsGetRoutes",
            "PRIVACY_GET_ROUTES": "PrivacyGetRoutes",
        }[route_name]
        self.assertEqual(ast.unparse(assignment.value.func), expected_factory)

    def _assert_write_route_owned(
        self,
        handler_method: str,
        route_name: str,
        forbidden_paths: tuple[str, ...],
        factory: str,
    ) -> ast.Module:
        assembly_tree = _parse(BACKEND_ROOT / "http_api" / "assembly.py")
        assembly = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HttpApiAssembly"
        )
        init = next(
            node
            for node in assembly.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        route_attr = route_name.lower()
        assignment = next(
            node
            for node in ast.walk(init)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == route_attr
                for target in node.targets
            )
        )
        expected_class = factory.split("(", 1)[0]
        self.assertIsInstance(assignment.value, ast.Call)
        self.assertEqual(ast.unparse(assignment.value.func), expected_class)
        if route_name in {"SETTINGS_PUT_ROUTES", "ATHLETE_PUT_ROUTES"}:
            handler = next(
                node
                for node in _request_handler_definition().body
                if isinstance(node, ast.FunctionDef) and node.name == handler_method
            )
            self.assertIn(
                "dependencies.route_dispatcher.handle_put", ast.unparse(handler)
            )
        else:
            post_routes = {
                "AUTH_POST_ROUTES",
                "PRIVACY_RESTORE_POST_ROUTES",
                "CHAT_CANCEL_POST_ROUTES",
                "COACH_ACTIONS_POST_ROUTES",
                "CHAT_POST_ROUTES",
                "TRANSCRIBE_POST_ROUTES",
                "PLANNING_COMMANDS_POST_ROUTES",
                "FEEDBACK_POST_ROUTES",
                "CHAT_STREAM_TRANSPORT",
                "SYNC_COMMAND_POST_ROUTE",
                "HISTORY_UNDO_POST_ROUTES",
                "DIAGNOSTICS_CAPTURE_POST_ROUTES",
                "PRIVACY_DELETE_POST_ROUTES",
                "NUTRITION_POST_ROUTES",
                "DIAGNOSTICS_DELETE_POST_ROUTES",
            }
            self.assertIn(route_name, post_routes)
            owner_attr = (
                "post_dispatcher"
                if route_name
                in {
                    "AUTH_POST_ROUTES",
                    "PRIVACY_RESTORE_POST_ROUTES",
                    "CHAT_CANCEL_POST_ROUTES",
                }
                else "authenticated_post_routes"
            )
            owner = next(
                node
                for node in ast.walk(init)
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute) and target.attr == owner_attr
                    for target in node.targets
                )
            )
            self.assertTrue(
                any(
                    isinstance(node, ast.Attribute) and node.attr == route_attr
                    for node in ast.walk(owner.value)
                )
            )
        paths = {
            node.value
            for node in ast.walk(assignment.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue(set(forbidden_paths).isdisjoint(paths))
        return assembly_tree

    def test_coach_get_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_get_route_owned("_handle_coach_get", "COACH_GET_ROUTES")

    def test_public_get_routes_are_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_public_get", "PUBLIC_GET_ROUTES"
        )
        self._assert_route_factories(
            server_tree,
            "PUBLIC_GET_ROUTES",
            [
                "runtime_maintenance.MAINTENANCE_GATE",
                "readiness_service",
                "session_auth_service",
                "PUBLIC_STATE.bootstrap_service",
            ],
        )

    def test_planning_get_routes_are_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_training_get",
            "PLANNING_GET_ROUTES",
        )
        self._assert_route_factories(
            server_tree,
            "PLANNING_GET_ROUTES",
            [
                "session_auth_service",
                "PUBLIC_STATE.plan_state_service",
                "PUBLIC_STATE.weather_state_service",
                "library_page_service",
            ],
        )

    def test_athlete_get_routes_are_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_training_get",
            "ATHLETE_GET_ROUTES",
        )
        self._assert_route_factories(
            server_tree,
            "ATHLETE_GET_ROUTES",
            [
                "session_auth_service",
                "PUBLIC_STATE.performance_state_service",
                "ATHLETE_DATA.profile",
                "PLANNING_DATA.competition",
                "PUBLIC_STATE.feedback_state_service",
                "COACH_CONTEXT.preview_service",
                "SETTINGS",
            ],
        )

    def test_sync_get_routes_are_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_sync_get",
            "SYNC_GET_ROUTES",
        )
        self._assert_route_factories(
            server_tree,
            "SYNC_GET_ROUTES",
            [
                "session_auth_service",
                "SYNC_JOB_QUEUE.service",
                "PUBLIC_STATE.sync_public_state_service",
                "ACTIVITY_READS.activity_read",
                "lambda: ATHLETE_CLOCK.now().date()",
                "ALL_SYNC_DAYS",
            ],
        )
        self.assertNotIn(
            "SYNC_JOB_RE",
            {node.id for node in ast.walk(server_tree) if isinstance(node, ast.Name)},
        )

    def test_state_events_get_route_owns_authenticated_sse_dispatch(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_sync_get", "STATE_EVENTS_GET_ROUTES"
        )
        self._assert_route_factories(
            server_tree,
            "STATE_EVENTS_GET_ROUTES",
            [
                "session_auth_service",
                "StateEventTransport(runtime_events.STATE_EVENT_BUFFER)",
            ],
        )
        route_source = (BACKEND_ROOT / "http_api" / "state_events_get.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())
        self.assertIn("require_auth(handler)", route_source)
        self.assertIn("_state_event_transport.handle(", route_source)

    def test_history_get_route_is_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_diagnostics_get",
            "HISTORY_GET_ROUTES",
        )
        self._assert_route_factories(
            server_tree,
            "HISTORY_GET_ROUTES",
            ["session_auth_service", "change_history_service"],
        )

    def test_history_undo_post_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_handle_data_post",
            "HISTORY_UNDO_POST_ROUTES",
            ("/api/change-history/undo/preview", "/api/change-history/undo"),
            "HistoryUndoPostRoutes(history_undo_service, COACH_PROPOSALS.creation_service)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "history_undo_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_coach_actions_post_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_handle_coach_post",
            "COACH_ACTIONS_POST_ROUTES",
            ("/api/coach/actions/confirm", "/api/coach/actions/execute"),
            "CoachActionsPostRoutes(COACH_PROPOSALS.confirmation_service, COACH_PROPOSALS.execution_service)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "coach_actions_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_chat_post_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_handle_coach_post",
            "CHAT_POST_ROUTES",
            ("/api/chat", "/api/chat/reset", "client_turn_id"),
            "ChatPostRoutes(COACH_BACKGROUND_JOBS.job_submission_service, COACH_CONVERSATION.reset_service, coach_attachments.MAX_REQUEST_BYTES)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "chat_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_chat_stream_lifecycle_is_owned_by_http_api_module(self) -> None:
        assembly_tree = _parse(BACKEND_ROOT / "http_api" / "assembly.py")
        handler = _request_handler_definition()
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef) and node.name == "handle_chat_stream"
                for node in handler.body
            )
        )
        dispatcher_source = (BACKEND_ROOT / "http_api" / "post_dispatch.py").read_text(
            encoding="utf-8"
        )
        dispatcher_tree = ast.parse(dispatcher_source)
        coach_post = next(
            node
            for node in ast.walk(dispatcher_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "handle_authenticated"
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and ast.unparse(node.func) == "self._chat_stream.handle"
                for node in ast.walk(coach_post)
            ),
            1,
        )
        assembly = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HttpApiAssembly"
        )
        assignment = next(
            node
            for node in ast.walk(assembly)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "chat_stream_transport"
                for target in node.targets
            )
        )
        self.assertEqual(ast.unparse(assignment.value.func), "CoachChatStreamTransport")
        self.assertIn("chat_stream_registry", ast.unparse(assignment.value))
        self.assertIn("coach_command_receipt_service", ast.unparse(assignment.value))
        route_source = (BACKEND_ROOT / "http_api" / "chat_stream.py").read_text(
            encoding="utf-8"
        )
        route_tree = ast.parse(route_source)
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom) and node.module == "server"
                for node in ast.walk(route_tree)
            )
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Import)
                and any(alias.name == "server" for alias in node.names)
                for node in ast.walk(route_tree)
            )
        )

    def test_transcribe_post_route_is_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_write_route_owned(
            "_handle_coach_post",
            "TRANSCRIBE_POST_ROUTES",
            ("/api/transcribe",),
            "TranscribePostRoutes(MODEL_TRANSPORT.audio_transcription_client)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "transcribe_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())
        self.assertIn("handler.read_audio_body()", route_source)
        self.assertNotIn("selected_ai_provider()", route_source)
        self.assertNotIn(
            "transcribe_audio",
            {
                node.name
                for node in ast.walk(server_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            },
        )

    def test_sync_command_post_transport_is_owned_by_http_api_module(self) -> None:
        _parse(SERVER_PATH)
        handler = _request_handler_definition()
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef) and node.name == "_handle_sync_post"
                for node in handler.body
            )
        )
        route_source = (BACKEND_ROOT / "http_api" / "sync_commands_post.py").read_text(
            encoding="utf-8"
        )
        route_tree = ast.parse(route_source)
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom) and node.module == "server"
                for node in ast.walk(route_tree)
            )
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Import)
                and any(alias.name == "server" for alias in node.names)
                for node in ast.walk(route_tree)
            )
        )

    def test_planning_commands_post_route_is_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_handle_coach_post",
            "PLANNING_COMMANDS_POST_ROUTES",
            ("/api/planning/commands",),
            "PlanningCommandsPostRoutes(coach_planning_command_service, lambda: COACH_CONVERSATION.provision_service())",
        )
        route_source = (
            BACKEND_ROOT / "http_api" / "planning_commands_post.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("server", route_source.casefold())

    def test_feedback_post_route_is_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_handle_coach_post",
            "FEEDBACK_POST_ROUTES",
            ("/api/feedback",),
            "FeedbackPostRoutes(ATHLETE_DATA.checkin)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "feedback_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_chat_cancel_post_route_is_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "do_POST",
            "CHAT_CANCEL_POST_ROUTES",
            ("/api/chat/cancel",),
            "ChatCancelPostRoutes(COACH_BACKGROUND_JOBS.cancellation_service)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "chat_cancel_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_privacy_restore_post_route_is_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "do_POST",
            "PRIVACY_RESTORE_POST_ROUTES",
            ("/api/privacy/restore",),
            "PrivacyRestorePostRoutes(session_auth_service, BACKUP_ASSEMBLY.restore_service, MAX_BACKUP_BYTES)",
        )
        route_source = (
            BACKEND_ROOT / "http_api" / "privacy_restore_post.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("server", route_source.casefold())

    def test_auth_post_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "do_POST",
            "AUTH_POST_ROUTES",
            ("/api/login", "/api/logout"),
            "AuthPostRoutes(session_auth_service, runtime_maintenance.MAINTENANCE_GATE)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "auth_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_privacy_delete_post_route_is_owned_by_http_api_module(self) -> None:
        server_tree = self._assert_write_route_owned(
            "_handle_data_post",
            "PRIVACY_DELETE_POST_ROUTES",
            ("/api/privacy/delete", "LOKALE DATEN LÖSCHEN"),
            "PrivacyDeletePostRoutes(PRIVACY_ASSEMBLY.delete_service)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "privacy_delete_post.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())
        self.assertNotIn(
            "PRIVACY_ASSEMBLY.delete_service().delete()", ast.unparse(server_tree)
        )

    def test_diagnostics_delete_post_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "do_POST",
            "DIAGNOSTICS_DELETE_POST_ROUTES",
            ("/api/logs/delete", "/api/diagnostics/delete"),
            "DiagnosticsDeletePostRoutes(recent_log_entries_service, diagnostic_report_service)",
        )
        route_source = (
            BACKEND_ROOT / "http_api" / "diagnostics_delete_post.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("server", route_source.casefold())

    def test_settings_put_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_do_PUT",
            "SETTINGS_PUT_ROUTES",
            (
                "/api/settings/model",
                "/api/settings/ai-provider",
                "/api/settings/thinking-level",
                "/api/settings/calendar-display",
            ),
            "SettingsPutRoutes(SETTINGS)",
        )

    def test_athlete_put_routes_are_owned_by_http_api_module(self) -> None:
        self._assert_write_route_owned(
            "_do_PUT",
            "ATHLETE_PUT_ROUTES",
            ("/api/athlete-context", "/api/profile"),
            "AthletePutRoutes(athlete_context_service, ATHLETE_DATA.profile, DB_LOCK)",
        )
        route_source = (BACKEND_ROOT / "http_api" / "athlete_put.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("server", route_source.casefold())

    def test_diagnostics_and_privacy_get_routes_are_owned_by_http_api_modules(
        self,
    ) -> None:
        server_tree = self._assert_get_route_owned(
            "_handle_diagnostics_get", "DIAGNOSTICS_GET_ROUTES"
        )
        self.assertNotIn(
            "_handle_diagnostics_get",
            {
                node.name
                for node in ast.walk(server_tree)
                if isinstance(node, ast.FunctionDef)
            },
        )
        self._assert_route_factories(
            server_tree,
            "DIAGNOSTICS_GET_ROUTES",
            [
                "session_auth_service",
                "DIAGNOSTICS_ASSEMBLY.recent_log_entries_service",
                "DIAGNOSTICS_ASSEMBLY.report_service",
            ],
        )
        self._assert_get_route_owned("_handle_diagnostics_get", "PRIVACY_GET_ROUTES")
        self._assert_route_factories(
            server_tree,
            "PRIVACY_GET_ROUTES",
            [
                "session_auth_service",
                "export_stream_transport",
                "PRIVACY_ASSEMBLY.delete_service",
            ],
        )
