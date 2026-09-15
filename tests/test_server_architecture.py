"""Static architecture guards for the server-monolith extraction.

The checks in this module intentionally parse source files instead of importing
the application.  Importing ``server`` initializes configuration and other
runtime state, which is outside the scope of an architecture check.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
SERVER_PATH = REPOSITORY_ROOT / "server.py"


# This is deliberately explicit.  These small, dependency-light helpers are
# backend-owned implementations, not server callbacks or compatibility
# wrappers, and must not be reintroduced in server.py.
MOVED_SYMBOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "backend.errors",
        (
            "AppError",
            "ClientDisconnected",
            "provider_error",
            "public_app_error_status",
            "INTERVALS_API_KEY_ERROR",
            "OPENAI_API_KEY_ERROR",
            "GEMINI_API_KEY_ERROR",
            "NOT_FOUND_ERROR",
            "INTERNAL_SERVER_ERROR",
            "COMPETITION_NOT_FOUND_ERROR",
            "COACH_ABORTED_ERROR",
            "STRUCTURED_AUTHORIZATION_ERROR",
            "INVALID_PLANNING_ID_ERROR",
            "CORRUPT_PLANNING_ERROR",
            "INVALID_LIBRARY_ID_ERROR",
            "CORRUPT_LIBRARY_ERROR",
            "INVALID_PLANNING_DATE_ERROR",
            "STALE_PLANNING_REVISION_ERROR",
            "UNSUPPORTED_BYDAY_ERROR",
            "PLANNED_CALENDAR_RECHECK_ERROR",
        ),
    ),
    ("backend.runtime.events", ("StateEventBuffer", "STATE_EVENT_BUFFER")),
    (
        "backend.runtime.maintenance",
        (
            "MaintenanceGate",
            "MAINTENANCE_GATE",
            "maintenance_operation",
            "claimed_maintenance_operation",
        ),
    ),
    (
        "backend.settings",
        (
            "SettingsService",
            "MODEL_OPTIONS",
            "GEMINI_MODEL_OPTIONS",
            "THINKING_LEVEL_OPTIONS",
            "CALENDAR_DISPLAY_DEFAULTS",
            "CALENDAR_DISPLAY_MAX_WEEKS",
            "available_ai_providers",
            "selected_ai_provider",
            "save_ai_provider",
            "available_model_options",
            "selected_model",
            "save_model",
            "available_thinking_level_options",
            "selected_thinking_level",
            "save_thinking_level",
            "calendar_display_settings",
            "save_calendar_display_settings",
        ),
    ),
    (
        "backend.observability",
        (
            "Redactor",
            "JsonLogFormatter",
            "configure_logging",
            "initialise_logging",
            "external_result_context",
            "safe_provider_path",
            "safe_url_netloc",
            "redact_text",
            "sanitize_log_value",
        ),
    ),
    ("backend.providers.http", ("ProviderHTTPError",)),
    ("backend.http_api.responses", ("json_bytes",)),
    ("backend.sync.windows", ("split_date_windows",)),
    ("backend.db.schema", ("database_table_names",)),
)


def _python_files(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_entrypoint_module(value: str | None) -> bool:
    return value in {"server", "__main__"} or bool(value and value.startswith("server."))


def _import_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str], set[str]]:
    """Return reliable aliases for sys.modules and dynamic import APIs."""
    sys_names = {"sys"}
    importlib_names = {"importlib"}
    import_functions = {"__import__"}
    sys_modules_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "sys":
                    sys_names.add(bound_name)
                elif alias.name == "importlib":
                    importlib_names.add(bound_name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if node.module == "sys" and alias.name == "modules":
                    sys_modules_names.add(bound_name)
                elif node.module == "importlib" and alias.name in {"import_module", "__import__"}:
                    import_functions.add(bound_name)
                elif node.module == "builtins" and alias.name == "__import__":
                    import_functions.add(bound_name)
    return sys_names, importlib_names, import_functions, sys_modules_names


def _is_sys_modules(node: ast.AST, sys_names: set[str], sys_modules_names: set[str]) -> bool:
    dotted = _dotted_name(node)
    return dotted in {f"{name}.modules" for name in sys_names} or dotted in sys_modules_names


def _entrypoint_namespace_expression(
    node: ast.AST,
    sys_names: set[str],
    sys_modules_names: set[str],
) -> bool:
    if isinstance(node, ast.Subscript) and _is_sys_modules(node.value, sys_names, sys_modules_names):
        return _is_entrypoint_module(_literal_string(node.slice))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if _is_sys_modules(node.func.value, sys_names, sys_modules_names) and node.func.attr in {
            "get",
            "setdefault",
            "pop",
            "__getitem__",
        }:
            return _is_entrypoint_module(_literal_string(node.args[0]) if node.args else None)
    return False


def _server_import_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    sys_names, importlib_names, import_functions, sys_modules_names = _import_aliases(tree)
    entrypoint_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _entrypoint_namespace_expression(
            node.value, sys_names, sys_modules_names
        ):
            entrypoint_bindings.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and _entrypoint_namespace_expression(
            node.value, sys_names, sys_modules_names
        ) and isinstance(node.target, ast.Name):
            entrypoint_bindings.add(node.target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_entrypoint_module(alias.name):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and _is_entrypoint_module(node.module):
            violations.append(
                f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: from {node.module} import ..."
            )
        elif isinstance(node, ast.Call):
            function = _dotted_name(node.func)
            imported_name = _literal_string(node.args[0]) if node.args else None
            dynamic_import_names = import_functions | {
                f"{name}.import_module" for name in importlib_names
            } | {f"{name}.__import__" for name in importlib_names}
            if function in dynamic_import_names and _is_entrypoint_module(imported_name):
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: {function}({imported_name!r})"
                )
            elif _entrypoint_namespace_expression(node, sys_names, sys_modules_names):
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: entry-point namespace lookup"
                )
            elif function in {"getattr", "hasattr"} and node.args and (
                isinstance(node.args[0], ast.Name) and node.args[0].id in entrypoint_bindings
            or _entrypoint_namespace_expression(node.args[0], sys_names, sys_modules_names)
            ):
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: {function} on entry-point namespace"
                )
        elif isinstance(node, ast.Subscript):
            if _is_sys_modules(node.value, sys_names, sys_modules_names):
                imported_name = _literal_string(node.slice)
                if _is_entrypoint_module(imported_name):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: sys.modules[{imported_name!r}]"
                    )
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in entrypoint_bindings:
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: entry-point attribute access"
                )
    return violations


def _top_level_implementations(tree: ast.Module) -> dict[str, int]:
    implementations: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                implementations[node.name] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    implementations[target.id] = node.lineno
    return implementations


class ServerArchitectureTests(unittest.TestCase):
    def test_backend_does_not_import_or_reach_server_namespace(self) -> None:
        violations: list[str] = []
        for path in _python_files(BACKEND_ROOT):
            violations.extend(_server_import_violations(path, _parse(path)))
        self.assertEqual(
            [],
            violations,
            "Backend modules must not import or dynamically access server.py:\n"
            + "\n".join(violations),
        )

    def test_server_does_not_redefine_extracted_public_symbols(self) -> None:
        implementations = _top_level_implementations(_parse(SERVER_PATH))
        violations = [
            f"{module}.{symbol} is redefined in server.py:{implementations[symbol]}"
            for module, symbols in MOVED_SYMBOLS
            for symbol in symbols
            if symbol in implementations
        ]
        self.assertEqual(
            [],
            violations,
            "server.py must remain a composition root for extracted symbols:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
