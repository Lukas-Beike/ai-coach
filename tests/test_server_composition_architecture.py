from __future__ import annotations

import ast
import unittest

try:
    from .test_server_architecture import (
        BACKEND_ROOT,
        REPOSITORY_ROOT,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
        _parse,
        _python_files,
        _request_handler_definition,
        _top_level_implementations,
    )
except ImportError:
    from test_server_architecture import (
        BACKEND_ROOT,
        REPOSITORY_ROOT,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
        _parse,
        _python_files,
        _request_handler_definition,
        _top_level_implementations,
    )


class ServerCompositionArchitectureTests(unittest.TestCase):
    def test_assembly_interfaces_stay_owner_scoped_and_bounded(self) -> None:
        violations: list[str] = []
        for path in _python_files(BACKEND_ROOT):
            tree = _parse(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or not node.name.endswith(
                    "Assembly"
                ):
                    continue
                initializer = next(
                    (
                        item
                        for item in node.body
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__"
                    ),
                    None,
                )
                if initializer is None:
                    continue
                count = len([arg for arg in initializer.args.args if arg.arg != "self"])
                count += len(initializer.args.kwonlyargs)
                if count > 5:
                    violations.append(
                        f"{path}:{initializer.lineno}: {node.name} has {count} constructor inputs"
                    )

        self.assertEqual(
            [],
            violations,
            "Assembly constructors must use typed owner groups instead of long parameter lists:\n"
            + "\n".join(violations),
        )

    def test_chat_history_http_projection_uses_coach_history_owner(self) -> None:
        source = (BACKEND_ROOT / "http_api" / "chat_page.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        service = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ChatHistoryPageService"
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                for node in ast.walk(service)
            )
        )
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and ast.unparse(node.func) == "self._conversation_history.page"
                for node in ast.walk(service)
            )
        )

    def test_request_handler_response_methods_only_delegate_socket_writes(self) -> None:
        _parse(SERVER_PATH)
        handler = _request_handler_definition()
        delegated_methods = {
            "send_sse_headers": "send_sse_headers",
            "send_sse_event": "send_sse_event",
            "send_json": "send_json",
            "send_file_stream": "send_file_stream",
            "send_bytes": "send_bytes",
            "send_static": "send_static",
        }
        for method_name, transport_method in delegated_methods.items():
            with self.subTest(method=method_name):
                method = next(
                    node
                    for node in handler.body
                    if isinstance(node, ast.FunctionDef) and node.name == method_name
                )
                calls = [
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and ast.unparse(node.func)
                    == f"self.dependencies.response_transport.{transport_method}"
                ]
                self.assertEqual(len(calls), 1)

    def test_post_handler_preserves_authentication_csrf_and_maintenance_order(
        self,
    ) -> None:
        _parse(SERVER_PATH)
        handler = _request_handler_definition()
        post = next(
            node
            for node in handler.body
            if isinstance(node, ast.FunctionDef) and node.name == "do_POST"
        )
        source = ast.unparse(post)
        ordered_calls = (
            "dependencies.post_dispatcher.handle_before_auth",
            "self.auth_service.require_auth",
            "self.auth_service.require_csrf",
            "dependencies.post_dispatcher.handle_before_maintenance",
            "dependencies.maintenance_gate.operation",
            "dependencies.post_dispatcher.handle_authenticated",
        )
        positions = [source.index(call) for call in ordered_calls]
        self.assertEqual(positions, sorted(positions))

    def test_chat_turn_has_no_server_adapter(self) -> None:
        implementations = _top_level_implementations(_parse(SERVER_PATH))
        self.assertNotIn("chat_with_coach", implementations)
        self.assertNotIn("coach_chat_turn_service", implementations)
        self.assertIn("COACH_TURNS", implementations)

    def test_training_plan_scope_prefix_is_owned_by_coach_authorization(self) -> None:
        server_tree = _parse(SERVER_PATH)
        self.assertFalse(
            any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "TRAINING_PLAN_SCOPE_PREFIX"
                    for target in node.targets
                )
                for node in server_tree.body
            )
        )
        authorization = (BACKEND_ROOT / "coach" / "authorization.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('TRAINING_PLAN_SCOPE_PREFIX = "training_plan:"', authorization)
        for module_name in (
            "dialogue_action.py",
            "planning_change_tools.py",
            "planning_action_tools.py",
        ):
            source = (BACKEND_ROOT / "coach" / module_name).read_text(encoding="utf-8")
            self.assertIn("TRAINING_PLAN_SCOPE_PREFIX", source)
            self.assertNotIn("training_plan_scope_prefix", source)

    def test_coach_tool_round_limit_is_owned_by_its_execution_service(self) -> None:
        server_tree = _parse(SERVER_PATH)
        self.assertFalse(
            any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "COACH_TOOL_MAX_ROUNDS"
                    for target in node.targets
                )
                for node in server_tree.body
            )
        )
        round_service = (BACKEND_ROOT / "coach" / "structured_tool_round.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("COACH_TOOL_MAX_ROUNDS = 12", round_service)

    def test_morning_battery_source_uses_backend_garmin_reader_instance(self) -> None:
        tree = _parse(SERVER_PATH)
        factory = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "morning_body_battery_service"
        )
        source = next(
            node
            for node in ast.walk(factory)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "MorningBatterySource"
        )

        self.assertIsInstance(source.args[1], ast.Call)
        self.assertIsInstance(source.args[1].func, ast.Name)
        self.assertEqual(source.args[1].func.id, "GarminMorningRemoteReader")
        self.assertNotIn("fetch_morning_body_battery", ast.unparse(factory))
        self.assertNotIn("provider_http.external_call", ast.unparse(factory))
        reader = (BACKEND_ROOT / "sync" / "garmin_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class GarminMorningRemoteReader:", reader)

    def test_athlete_clock_receives_profile_service_without_server_callback(
        self,
    ) -> None:
        tree = _parse(SERVER_PATH)
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ATHLETE_CLOCK"
                for target in node.targets
            )
        )

        self.assertIsInstance(assignment.value, ast.Call)
        self.assertEqual(ast.unparse(assignment.value.func), "AthleteLocalClock")
        self.assertEqual(
            [ast.unparse(argument) for argument in assignment.value.args],
            ["ATHLETE_PROFILE_SERVICE"],
        )
        self.assertEqual(assignment.value.keywords, [])

    def test_session_auth_cache_state_is_owned_by_http_api_auth(self) -> None:
        auth_tree = _parse(BACKEND_ROOT / "http_api" / "auth.py")
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef)
                and node.name == "SessionAuthServiceCache"
                for node in auth_tree.body
            )
        )
        self.assertTrue(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "get_session_auth_service"
                for node in auth_tree.body
            )
        )
        self.assertTrue(
            any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "RATE_LIMITER"
                    for target in node.targets
                )
                and ast.unparse(node.value) == "RateLimiter()"
                for node in auth_tree.body
            )
        )
        server_tree = _parse(SERVER_PATH)
        server_assignments = {
            target.id
            for node in server_tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        self.assertTrue(
            {
                "SESSION_AUTH_SERVICE",
                "SESSION_AUTH_SIGNATURE",
                "RATE_LIMITER",
            }.isdisjoint(server_assignments)
        )
        auth_imports = [
            alias.name
            for node in server_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "backend.http_api.auth"
            for alias in node.names
        ]
        self.assertIn("get_session_auth_service", auth_imports)
        self.assertNotIn("RATE_LIMITER", auth_imports)
        self.assertNotIn("SESSION_AUTH_SERVICE_CACHE", auth_imports)

    def test_provider_state_service_cache_is_owned_by_provider_state(self) -> None:
        state_tree = _parse(BACKEND_ROOT / "providers" / "state.py")
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef)
                and node.name == "ProviderStateServiceCache"
                for node in state_tree.body
            )
        )
        self.assertTrue(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "get_provider_state_service"
                for node in state_tree.body
            )
        )
        server_tree = _parse(SERVER_PATH)
        server_assignments = {
            target.id
            for node in server_tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("PROVIDER_STATE_SERVICE", server_assignments)
        service_factory = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "provider_state_service"
        )
        self.assertIn(
            "provider_state.get_provider_state_service",
            ast.unparse(service_factory),
        )

    def test_provider_refresh_tracker_cache_is_owned_by_sync_refresh(self) -> None:
        refresh_tree = _parse(BACKEND_ROOT / "sync" / "refresh.py")
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef)
                and node.name == "ProviderRefreshTrackerCache"
                for node in refresh_tree.body
            )
        )
        assembly_tree = _parse(BACKEND_ROOT / "sync" / "assembly.py")
        assembly = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ProviderSyncAssembly"
        )
        tracker_factory = next(
            node
            for node in assembly.body
            if isinstance(node, ast.FunctionDef) and node.name == "refresh_tracker"
        )
        self.assertIn(
            "refresh.PROVIDER_REFRESH_TRACKER_CACHE.get",
            ast.unparse(tracker_factory),
        )
        server_tree = _parse(SERVER_PATH)
        provider_sync = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PROVIDER_SYNC"
                for target in node.targets
            )
        )
        self.assertIn("ProviderSyncAssembly", ast.unparse(provider_sync.value))
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name
                in {
                    "provider_refresh_tracker",
                    "sync_operation_observer",
                    "provider_freshness_service",
                }
                for node in server_tree.body
            )
        )

    def test_provider_http_client_cache_is_owned_by_provider_transport(self) -> None:
        transport_tree = _parse(BACKEND_ROOT / "providers" / "transport_assembly.py")
        assembly = next(
            node
            for node in transport_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ProviderTransportAssembly"
        )
        json_client = next(
            node
            for node in assembly.body
            if isinstance(node, ast.FunctionDef) and node.name == "json_http_client"
        )
        self.assertIn(
            "provider_http.JSON_HTTP_CLIENT_CACHE.get",
            ast.unparse(json_client),
        )
        transport_module = _parse(BACKEND_ROOT / "providers" / "http.py")
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef) and node.name == "JsonHttpClientCache"
                for node in transport_module.body
            )
        )
        server_tree = _parse(SERVER_PATH)
        provider_transport = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PROVIDER_TRANSPORT"
                for target in node.targets
            )
        )
        self.assertIn(
            "ProviderTransportAssembly",
            ast.unparse(provider_transport.value),
        )
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name in {"provider_http_client", "intervals_client"}
                for node in server_tree.body
            )
        )

    def test_snapshot_reader_and_intervals_operation_are_composed_explicitly(
        self,
    ) -> None:
        server_tree = _parse(SERVER_PATH)
        athlete_data = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ATHLETE_DATA"
                for target in node.targets
            )
        )
        self.assertIn(
            "snapshot_reader=SnapshotRepositoryReader(SNAPSHOT_REPOSITORY)",
            ast.unparse(athlete_data.value),
        )

        provider_transport = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PROVIDER_TRANSPORT"
                for target in node.targets
            )
        )
        self.assertIn(
            "operation=INTERVALS_RESYNC_GATE.operation",
            ast.unparse(provider_transport.value),
        )

        transport_tree = _parse(BACKEND_ROOT / "providers" / "transport_assembly.py")
        assembly = next(
            node
            for node in transport_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ProviderTransportAssembly"
        )
        client_factory = next(
            node
            for node in assembly.body
            if isinstance(node, ast.FunctionDef) and node.name == "intervals_client"
        )
        self.assertIn(
            "operation=self._intervals_operation", ast.unparse(client_factory)
        )

    def test_weather_service_cache_is_owned_by_weather_service_module(self) -> None:
        weather_tree = _parse(BACKEND_ROOT / "weather" / "service.py")
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef) and node.name == "WeatherServiceCache"
                for node in weather_tree.body
            )
        )
        assembly_tree = _parse(BACKEND_ROOT / "weather" / "assembly.py")
        assembly = next(
            node
            for node in assembly_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "WeatherAssembly"
        )
        service_method = next(
            node
            for node in assembly.body
            if isinstance(node, ast.FunctionDef) and node.name == "service"
        )
        self.assertIn(
            "weather.WEATHER_SERVICE_CACHE.get",
            ast.unparse(service_method),
        )
        server_tree = _parse(SERVER_PATH)
        weather_assembly = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "WEATHER_ASSEMBLY"
                for target in node.targets
            )
        )
        self.assertIn("WeatherAssembly", ast.unparse(weather_assembly.value))
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name in {"weather_service", "weather_sync_service"}
                for node in server_tree.body
            )
        )

    def test_morning_battery_cache_is_owned_by_performance_service_module(self) -> None:
        performance_tree = _parse(
            BACKEND_ROOT / "performance" / "morning_battery_service.py"
        )
        self.assertTrue(
            any(
                isinstance(node, ast.ClassDef)
                and node.name == "MorningBodyBatteryServiceCache"
                for node in performance_tree.body
            )
        )
        server_tree = _parse(SERVER_PATH)
        server_assignments = {
            target.id
            for node in server_tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("MORNING_BODY_BATTERY_SERVICE", server_assignments)
        self.assertNotIn("MORNING_BODY_BATTERY_CONFIG_ID", server_assignments)
        self.assertNotIn(
            "reset_provider_runtime",
            {
                node.name
                for node in server_tree.body
                if isinstance(node, ast.FunctionDef)
            },
        )
        service_factory = next(
            node
            for node in server_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "morning_body_battery_service"
        )
        self.assertIn(
            "MORNING_BODY_BATTERY_SERVICE_CACHE.get",
            ast.unparse(service_factory),
        )

    def test_server_composition_bodies_do_not_own_domain_or_io_logic(self) -> None:
        tree = _parse(SERVER_PATH)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        control_flow = {
            name
            for name, function in functions.items()
            if any(
                isinstance(
                    node,
                    (
                        ast.If,
                        ast.For,
                        ast.AsyncFor,
                        ast.While,
                        ast.Try,
                        ast.With,
                        ast.AsyncWith,
                        ast.Match,
                    ),
                )
                for node in ast.walk(function)
            )
        }
        self.assertEqual(SERVER_COMPOSITION_CONTROL_FLOW, control_flow)

        forbidden_calls = {
            "execute",
            "executemany",
            "fetchone",
            "fetchall",
            "urlopen",
            "send_request",
            "request",
            "post",
            "put",
            "delete",
            "open",
            "read",
            "write",
            "read_bytes",
            "write_bytes",
            "read_text",
            "write_text",
            "connect",
        }
        violations = [
            f"{function.name}:{node.lineno}:{ast.unparse(node.func)}"
            for function in functions.values()
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_calls
        ]
        self.assertEqual([], violations)

    def test_browser_fixture_does_not_patch_removed_response_functions(self) -> None:
        fixture = REPOSITORY_ROOT / "e2e" / "fixture_runtime.py"
        removed = {
            "responses_request",
            "responses_background_request",
            "responses_stream_request",
        }
        patched = [
            target.attr
            for node in ast.walk(_parse(fixture))
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute)
            and ast.unparse(target.value) in {"server", "server.COACH_CONVERSATION"}
        ]
        self.assertTrue(removed.isdisjoint(patched))
        self.assertIn("response_transport", patched)

    def test_request_handler_does_not_reintroduce_state_event_orchestration(
        self,
    ) -> None:
        request_handler = _request_handler_definition()
        methods = {
            node.name
            for node in request_handler.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(
            {"send_state_event_batch", "handle_state_events"}.isdisjoint(methods)
        )
