"""Typed AST and import-graph analysis helpers for architecture tests."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

try:
    from .architecture_registry import BACKEND_ROOT, HANDLER_PATH
except ImportError:
    from architecture_registry import BACKEND_ROOT, HANDLER_PATH


def python_files(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def request_handler_definition() -> ast.ClassDef:
    return next(
        node
        for node in parse_python(HANDLER_PATH).body
        if isinstance(node, ast.ClassDef) and node.name == "RequestHandler"
    )


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def is_entrypoint_module(value: str | None) -> bool:
    return value in {"server", "__main__"} or bool(
        value and value.startswith("server.")
    )


def import_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str], set[str]]:
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
                elif (
                    node.module == "importlib"
                    and alias.name in {"import_module", "__import__"}
                ) or (node.module == "builtins" and alias.name == "__import__"):
                    import_functions.add(bound_name)
    return sys_names, importlib_names, import_functions, sys_modules_names


def is_sys_modules(
    node: ast.AST, sys_names: set[str], sys_modules_names: set[str]
) -> bool:
    dotted = dotted_name(node)
    return (
        dotted in {f"{name}.modules" for name in sys_names}
        or dotted in sys_modules_names
    )


def entrypoint_namespace_expression(
    node: ast.AST,
    sys_names: set[str],
    sys_modules_names: set[str],
) -> bool:
    if isinstance(node, ast.Subscript) and is_sys_modules(
        node.value, sys_names, sys_modules_names
    ):
        return is_entrypoint_module(literal_string(node.slice))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and is_sys_modules(node.func.value, sys_names, sys_modules_names)
        and node.func.attr in {"get", "setdefault", "pop", "__getitem__"}
    ):
        return is_entrypoint_module(literal_string(node.args[0]) if node.args else None)
    return False


def server_import_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    sys_names, importlib_names, import_functions, sys_modules_names = import_aliases(
        tree
    )
    entrypoint_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and entrypoint_namespace_expression(
            node.value, sys_names, sys_modules_names
        ):
            entrypoint_bindings.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif (
            isinstance(node, ast.AnnAssign)
            and entrypoint_namespace_expression(
                node.value, sys_names, sys_modules_names
            )
            and isinstance(node.target, ast.Name)
        ):
            entrypoint_bindings.add(node.target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if is_entrypoint_module(alias.name):
                    violations.append(
                        f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and is_entrypoint_module(node.module):
            violations.append(
                f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: from {node.module} import ..."
            )
        elif isinstance(node, ast.Call):
            function = dotted_name(node.func)
            imported_name = literal_string(node.args[0]) if node.args else None
            dynamic_import_names = (
                import_functions
                | {f"{name}.import_module" for name in importlib_names}
                | {f"{name}.__import__" for name in importlib_names}
            )
            if function in dynamic_import_names and is_entrypoint_module(imported_name):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: {function}({imported_name!r})"
                )
            elif entrypoint_namespace_expression(node, sys_names, sys_modules_names):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: entry-point namespace lookup"
                )
            elif (
                function in {"getattr", "hasattr"}
                and node.args
                and (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id in entrypoint_bindings
                    or entrypoint_namespace_expression(
                        node.args[0], sys_names, sys_modules_names
                    )
                )
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: {function} on entry-point namespace"
                )
        elif isinstance(node, ast.Subscript):
            if is_sys_modules(node.value, sys_names, sys_modules_names):
                imported_name = literal_string(node.slice)
                if is_entrypoint_module(imported_name):
                    violations.append(
                        f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: sys.modules[{imported_name!r}]"
                    )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in entrypoint_bindings
        ):
            violations.append(
                f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: entry-point attribute access"
            )
    return violations


def runtime_import_cycles(backend_root: Path) -> list[tuple[str, ...]]:
    """Find eager backend import cycles, excluding type-only and local imports."""
    modules: dict[str, Path] = {}
    for path in python_files(backend_root):
        relative = path.relative_to(backend_root).with_suffix("")
        parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        modules["backend" + ("." + ".".join(parts) if parts else "")] = path

    graph: dict[str, set[str]] = {name: set() for name in modules}

    def eager_nodes(nodes: list[ast.stmt]) -> Iterable[ast.AST]:
        for node in nodes:
            yield node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.If):
                test = ast.unparse(node.test)
                if test in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
                    continue
                yield from eager_nodes(node.body)
                yield from eager_nodes(node.orelse)
            elif isinstance(node, (ast.Try, ast.TryStar)):
                yield from eager_nodes(node.body)
                for handler in node.handlers:
                    yield from eager_nodes(handler.body)
                yield from eager_nodes(node.orelse)
                yield from eager_nodes(node.finalbody)

    for name, path in modules.items():
        tree = parse_python(path)
        for node in eager_nodes(tree.body):
            targets: set[str] = set()
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    current = name.split(".")
                    package = current if path.name == "__init__.py" else current[:-1]
                    base = package[: len(package) - node.level + 1]
                    imported = node.module.split(".") if node.module else []
                    target = ".".join(base + imported)
                else:
                    target = node.module or ""
                if target:
                    targets.add(target)
                for alias in node.names:
                    child = f"{target}.{alias.name}" if target else alias.name
                    if child in modules:
                        targets.add(child)
            graph[name].update(target for target in targets if target in modules)

    cycles: set[tuple[str, ...]] = set()
    active: list[str] = []
    active_set: set[str] = set()
    complete: set[str] = set()

    def visit(name: str) -> None:
        if name in active_set:
            cycle = active[active.index(name) :]
            rotations = [
                tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))
            ]
            cycles.add(min(rotations))
            return
        if name in complete:
            return
        active.append(name)
        active_set.add(name)
        for target in sorted(graph[name]):
            visit(target)
        active.pop()
        active_set.remove(name)
        complete.add(name)

    for name in sorted(graph):
        visit(name)
    return sorted(cycles)


def top_level_implementations(tree: ast.Module) -> dict[str, int]:
    implementations: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            implementations[node.name] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name):
                    implementations[target.id] = node.lineno
    return implementations
