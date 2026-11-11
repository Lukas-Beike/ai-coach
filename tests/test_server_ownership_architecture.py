"""Ownership and extraction guards for the server composition root."""

from __future__ import annotations

import ast
import unittest

try:
    from .architecture_analysis import (
        parse_python as _parse,
    )
    from .architecture_analysis import (
        python_files as _python_files,
    )
    from .architecture_analysis import (
        top_level_implementations as _top_level_implementations,
    )
    from .architecture_registry import (
        BACKEND_ROOT,
        FORBIDDEN_SERVER_SYMBOLS,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
    )
except ImportError:
    from architecture_analysis import (
        parse_python as _parse,
    )
    from architecture_analysis import (
        python_files as _python_files,
    )
    from architecture_analysis import (
        top_level_implementations as _top_level_implementations,
    )
    from architecture_registry import (
        BACKEND_ROOT,
        FORBIDDEN_SERVER_SYMBOLS,
        SERVER_COMPOSITION_CONTROL_FLOW,
        SERVER_PATH,
    )


class ServerOwnershipArchitectureTests(unittest.TestCase):
    def test_server_does_not_redefine_backend_symbols(self) -> None:
        server_tree = _parse(SERVER_PATH)
        implementations = _top_level_implementations(server_tree)
        # A module logger is a per-module convention, not a moved implementation.
        loggers = {
            target.id
            for node in server_tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and ast.unparse(node.value.func) == "logging.getLogger"
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        backend_owners: dict[str, str] = {}
        for path in _python_files(BACKEND_ROOT):
            for symbol in _top_level_implementations(_parse(path)):
                backend_owners.setdefault(
                    symbol, path.relative_to(BACKEND_ROOT.parent).as_posix()
                )
        self.assertIn("PLANNED_WORKOUT_LABEL", backend_owners, "backend scan empty")
        violations = [
            f"{backend_owners[symbol]} defines {symbol}, redefined in server.py:{line}"
            for symbol, line in implementations.items()
            if symbol in backend_owners and symbol not in loggers
        ]
        violations.extend(
            f"legacy extracted symbol {symbol} is redefined in server.py:{implementations[symbol]}"
            for symbol in FORBIDDEN_SERVER_SYMBOLS
            if symbol in implementations
        )
        self.assertEqual(
            [],
            violations,
            "server.py must remain a composition root; import backend symbols "
            "instead of redefining them:\n" + "\n".join(violations),
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


if __name__ == "__main__":
    unittest.main()
