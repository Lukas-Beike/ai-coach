"""Ownership and extraction guards for the server composition root."""

from __future__ import annotations

import ast
import unittest

try:
    from .architecture_analysis import (
        parse_python as _parse,
    )
    from .architecture_analysis import (
        top_level_implementations as _top_level_implementations,
    )
    from .architecture_registry import (
        BACKEND_ROOT,
        FORBIDDEN_SERVER_SYMBOLS,
        MOVED_SYMBOLS,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
    )
except ImportError:
    from architecture_analysis import (
        parse_python as _parse,
    )
    from architecture_analysis import (
        top_level_implementations as _top_level_implementations,
    )
    from architecture_registry import (
        BACKEND_ROOT,
        FORBIDDEN_SERVER_SYMBOLS,
        MOVED_SYMBOLS,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
    )


class ServerOwnershipArchitectureTests(unittest.TestCase):
    def test_server_does_not_redefine_extracted_public_symbols(self) -> None:
        implementations = _top_level_implementations(_parse(SERVER_PATH))
        violations = [
            f"{module}.{symbol} is redefined in server.py:{implementations[symbol]}"
            for module, symbols in MOVED_SYMBOLS
            for symbol in symbols
            if symbol in implementations
        ]
        violations.extend(
            f"legacy extracted symbol {symbol} is redefined in server.py:{implementations[symbol]}"
            for symbol in FORBIDDEN_SERVER_SYMBOLS
            if symbol in implementations
        )
        self.assertEqual(
            [],
            violations,
            "server.py must remain a composition root for extracted symbols:\n"
            + "\n".join(violations),
        )

    def test_server_definitions_are_composition_factories_or_lifecycle(self) -> None:
        tree = _parse(SERVER_PATH)
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertEqual(
            [], classes, "Application and HTTP classes belong in backend owners."
        )

        functions = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertGreater(len(functions), 0)
        for function in functions:
            nested_implementation = [
                node
                for node in ast.walk(function)
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and node is not function
            ]
            self.assertEqual(
                [], nested_implementation, f"{function.name} defines nested behavior"
            )

            if function.name in SERVER_COMPOSITION_CONTROL_FLOW:
                continue
            statements = [
                node
                for node in function.body
                if not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                )
            ]
            self.assertTrue(
                statements, f"{function.name} must return its composed service"
            )
            self.assertTrue(
                all(
                    isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return))
                    for node in statements
                ),
                f"{function.name} must stay a straight-line composition factory",
            )

    def test_intervals_client_does_not_retain_snapshot_use_cases(self) -> None:
        intervals_client = next(
            node
            for node in _parse(BACKEND_ROOT / "providers" / "intervals_client.py").body
            if isinstance(node, ast.ClassDef) and node.name == "IntervalsClient"
        )
        methods = {
            node.name
            for node in intervals_client.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(
            {"fetch_snapshot", "fetch_performance_snapshot"}.isdisjoint(methods)
        )

    def test_intervals_sync_service_uses_bounded_owner_dependencies(self) -> None:
        intervals_module = _parse(BACKEND_ROOT / "sync" / "intervals.py")
        service = next(
            node
            for node in intervals_module.body
            if isinstance(node, ast.ClassDef) and node.name == "IntervalsSyncService"
        )
        initializer = next(
            node
            for node in service.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        self.assertLessEqual(len(initializer.args.args) - 1, 7)


if __name__ == "__main__":
    unittest.main()
