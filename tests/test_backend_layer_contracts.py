"""Static import direction and HTTP persistence ratchets.

Pending debt is keyed by exact source/target imports or scoped execution calls.
Removing debt requires shrinking the baseline; additions require an ownership
fix. All import nodes, including type-only and lazy imports, are inspected.
Literal dynamic server access uses the existing namespace guard. These checks
do not prove the absence of runtime cycles or arbitrary computed imports.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from .architecture_analysis import (
        server_import_violations as _server_import_violations,
    )
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_analysis import (
        server_import_violations as _server_import_violations,
    )
    from architecture_registry import BACKEND_ROOT

REPOSITORY_ROOT = BACKEND_ROOT.parent
DOMAIN_ROOTS = frozenset(
    f"backend.{name}"
    for name in (
        "activities",
        "athlete",
        "backup",
        "calendar",
        "coach",
        "diagnostics",
        "history",
        "nutrition",
        "performance",
        "planning",
        "sync",
        "weather",
    )
)
SHARED_ROOTS = frozenset(
    f"backend.{name}"
    for name in (
        "canonical",
        "change_history",
        "config",
        "errors",
        "observability",
        "pagination",
        "privacy",
        "settings",
    )
)
PERMITTED_IMPORTS_BY_LAYER = {
    "providers": frozenset(
        {
            "backend.providers",
            "backend.canonical",
            "backend.config",
            "backend.errors",
            "backend.observability",
            "backend.runtime.clock",
            "backend.runtime.ports",
            "backend.runtime.socket_deadline",
        }
    ),
    "canonical": frozenset({"backend.canonical"}),
    "http_api": DOMAIN_ROOTS | SHARED_ROOTS | {"backend.http_api", "backend.runtime"},
    "domain": DOMAIN_ROOTS
    | SHARED_ROOTS
    | {"backend.db", "backend.providers", "backend.runtime"},
    "db": SHARED_ROOTS | {"backend.db", "backend.runtime"},
    "runtime": SHARED_ROOTS | {"backend.runtime"},
    "shared": DOMAIN_ROOTS
    | SHARED_ROOTS
    | {"backend.db", "backend.providers", "backend.runtime"},
}

IMPORT_DEBT_BASELINE = frozenset(
    {
        ("backend/http_api/auth.py", "backend.db.manager"),
        ("backend/http_api/bootstrap_state.py", "backend.db.manager"),
        ("backend/http_api/library_page.py", "backend.db"),
        ("backend/http_api/public_plan.py", "backend.db.manager"),
        ("backend/http_api/public_state.py", "backend.db.manager"),
        ("backend/http_api/readiness.py", "backend.db.manager"),
        ("backend/http_api/readiness.py", "backend.db.schema"),
        ("backend/http_api/state_prelude.py", "backend.db.manager"),
        ("backend/http_api/state_versions.py", "backend.db"),
    }
)

DOMAIN_EXECUTE_CALLS = {
    (
        "backend/http_api/coach_actions_post.py",
        "CoachActionsPostRoutes.handle",
        "self._coach_proposal_execution_service().execute",
    ): 1,
    (
        "backend/http_api/planning_commands_post.py",
        "PlanningCommandsPostRoutes.handle",
        "self._coach_planning_command_service().execute",
    ): 1,
    (
        "backend/http_api/sync_commands_post.py",
        "SyncCommandPostRoute.handle",
        "endpoint.execute",
    ): 1,
}


def _module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _module_names(root: Path) -> set[str]:
    return {_module_name(path, root) for path in (root / "backend").rglob("*.py")}


def _resolve_from_import(
    source: str,
    node: ast.ImportFrom,
    modules: set[str],
    *,
    is_package: bool = False,
) -> set[str]:
    if node.level:
        package = source.split(".") if is_package else source.split(".")[:-1]
        if node.level > len(package):
            raise ValueError(f"Relative import escapes package: {source}")
        base_parts = package[: len(package) - node.level + 1]
        if node.module:
            base_parts.extend(node.module.split("."))
        base = ".".join(base_parts)
    else:
        base = node.module or ""
    targets: set[str] = set()
    for alias in node.names:
        candidate = f"{base}.{alias.name}" if base else alias.name
        targets.add(candidate if candidate in modules else base)
    return targets


def _imports(
    source: str,
    tree: ast.AST,
    modules: set[str],
    *,
    is_package: bool = False,
) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.update(
                _resolve_from_import(
                    source,
                    node,
                    modules,
                    is_package=is_package,
                )
            )
    return {
        target
        for target in targets
        if target in {"backend", "server", "__main__"}
        or target.startswith(("backend.", "server."))
    }


def _layer(source: str) -> str:
    for layer in ("canonical", "providers", "http_api", "db", "runtime"):
        if source == f"backend.{layer}" or source.startswith(f"backend.{layer}."):
            return layer
    if any(source == root or source.startswith(root + ".") for root in DOMAIN_ROOTS):
        return "domain"
    return "shared"


def _import_violations(root: Path) -> set[tuple[str, str]]:
    modules = _module_names(root)
    violations = set()
    for path in sorted((root / "backend").rglob("*.py")):
        source = _module_name(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        permitted = PERMITTED_IMPORTS_BY_LAYER[_layer(source)]
        for target in _imports(
            source, tree, modules, is_package=path.name == "__init__.py"
        ):
            if target != "backend" and not any(
                target == allowed or target.startswith(allowed + ".")
                for allowed in permitted
            ):
                violations.add((path.relative_to(root).as_posix(), target))
    return violations


def _package_import_edges(
    root: Path, *, include_function_imports: bool = True
) -> set[tuple[str, str]]:
    modules = _module_names(root)
    edges = set()
    for path in sorted((root / "backend").rglob("*.py")):
        source = _module_name(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not include_function_imports:

            class ModuleImports(ast.NodeTransformer):
                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    return None

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                    return None

            tree = ModuleImports().visit(tree)
        source_package = ".".join(source.split(".")[:2])
        for target in _imports(
            source, tree, modules, is_package=path.name == "__init__.py"
        ):
            target_package = ".".join(target.split(".")[:2])
            if target.startswith("backend.") and source_package != target_package:
                edges.add((source_package, target_package))
    return edges


def _package_import_cycles(edges: set[tuple[str, str]]) -> set[tuple[str, ...]]:
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
    cycles: set[tuple[str, ...]] = set()

    def visit(start: str, current: str, path: tuple[str, ...]) -> None:
        for target in graph.get(current, set()):
            if target == start:
                cycles.add(path)
            elif target > start and target not in path:
                visit(start, target, (*path, target))

    for source in sorted(graph):
        visit(source, source, (source,))
    return cycles


def _execute_calls(tree: ast.AST, relative: str) -> Counter[tuple[str, str, str]]:
    """Collect every execute call regardless of receiver name or SQL spelling."""
    sites: Counter[tuple[str, str, str]] = Counter()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "execute",
                "executemany",
                "executescript",
            }:
                sites[
                    (
                        relative,
                        ".".join(self.scope) or "<module>",
                        ast.unparse(node.func),
                    )
                ] += 1
            self.generic_visit(node)

    Visitor().visit(tree)
    return sites


def _http_execute_calls(root: Path) -> Counter[tuple[str, str, str]]:
    sites: Counter[tuple[str, str, str]] = Counter()
    for path in sorted((root / "backend" / "http_api").rglob("*.py")):
        sites.update(
            _execute_calls(
                ast.parse(path.read_text(encoding="utf-8")),
                path.relative_to(root).as_posix(),
            )
        )
    return sites


def _sql_candidates(
    calls: Counter[tuple[str, str, str]],
    service_calls: dict[tuple[str, str, str], int],
) -> Counter[tuple[str, str, str]]:
    """Exclude only reviewed, counted service dispatches at their exact scopes.

    Unknown execute calls are persistence candidates. No variable name grants
    an exemption, and every executemany/executescript call remains a candidate.
    """
    return calls - Counter(service_calls)


def _http_sql_literals(root: Path) -> list[tuple[str, str]]:
    literals: list[tuple[str, str]] = []
    sql_prefixes = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "WITH ")
    for path in sorted((root / "backend" / "http_api").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in {"execute", "executemany", "executescript"}:
                continue
            arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
            for argument in arguments:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and argument.value.lstrip().upper().startswith(sql_prefixes)
                ):
                    literals.append((relative, argument.value))
    return literals


CANONICAL_PACKAGE = "backend.canonical"


def _canonical_import_allowed(target: str) -> bool:
    top = target.split(".", 1)[0]
    return (
        top in sys.stdlib_module_names
        or target == CANONICAL_PACKAGE
        or target.startswith(CANONICAL_PACKAGE + ".")
    )


def _import_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [node.module or ""]
        if node.level == 1:
            # Package-relative imports stay inside backend.canonical.
            return []
        return ["." * node.level + (node.module or "")]
    return []


def _canonical_stdlib_violations(package_root: Path) -> list[str]:
    """Return imports that leave the standard library and backend.canonical."""
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(package_root.parent).as_posix()
        for node in ast.walk(tree):
            violations.extend(
                f"{relative}: {target}"
                for target in _import_targets(node)
                if not _canonical_import_allowed(target)
            )
    return sorted(violations)


class BackendLayerContractTests(unittest.TestCase):
    def test_athlete_has_no_domain_package_dependencies(self) -> None:
        self.assertEqual(
            set(),
            {
                target
                for source, target in _package_import_edges(REPOSITORY_ROOT)
                if source == "backend.athlete" and target in DOMAIN_ROOTS
            },
        )

    def test_package_import_cycles_match_shrinking_baseline(self) -> None:
        baseline = json.loads(
            (
                Path(__file__).resolve().parent / "fixtures/package_import_cycles.json"
            ).read_text(encoding="utf-8")
        )
        for mode, include_functions in (("module", False), ("all", True)):
            with self.subTest(mode=mode):
                cycles = _package_import_cycles(
                    _package_import_edges(
                        REPOSITORY_ROOT, include_function_imports=include_functions
                    )
                )
                self.assertEqual(
                    {tuple(cycle) for cycle in baseline[mode]},
                    cycles,
                    "Package imports must be cycle-free; shrink the explicit remaining cycle baseline when debt is resolved.",
                )

    def test_cycle_detection_includes_lazy_relative_and_type_only_imports(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                "backend/activities/read.py": "def load():\n    from ..performance import metrics\n",
                "backend/performance/metrics.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from backend.activities import read\n",
            }
            for relative, text in sources.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                set(),
                _package_import_cycles(
                    _package_import_edges(root, include_function_imports=False)
                ),
            )
            self.assertEqual(
                {("backend.activities", "backend.performance")},
                _package_import_cycles(_package_import_edges(root)),
            )

    def test_backend_import_directions_match_pending_baseline(self) -> None:
        violations = _import_violations(REPOSITORY_ROOT)
        self.assertEqual(
            IMPORT_DEBT_BASELINE,
            violations,
            "Fix new edges; shrink IMPORT_DEBT_BASELINE when existing debt is removed.",
        )
        server_violations = [
            violation
            for path in BACKEND_ROOT.rglob("*.py")
            for violation in _server_import_violations(
                path,
                ast.parse(path.read_text(encoding="utf-8")),
            )
        ]
        self.assertEqual([], server_violations)

    def test_relative_absolute_package_and_lazy_imports(self) -> None:
        modules = {
            "backend.providers",
            "backend.providers.context",
            "backend.providers.child",
            "backend.context",
        }
        cases = (
            (
                "from backend.providers.context import symbol",
                "backend.providers.adapter",
                False,
                {"backend.providers.context"},
            ),
            (
                "from backend.providers import context",
                "backend.providers.adapter",
                False,
                {"backend.providers.context"},
            ),
            (
                "from . import context",
                "backend.providers.adapter",
                False,
                {"backend.providers.context"},
            ),
            (
                "from .context import symbol",
                "backend.providers.adapter",
                False,
                {"backend.providers.context"},
            ),
            (
                "from ..context import symbol",
                "backend.providers.adapter",
                False,
                {"backend.context"},
            ),
            (
                "from .context import symbol",
                "backend.providers",
                True,
                {"backend.providers.context"},
            ),
            (
                "from ..context import symbol",
                "backend.providers",
                True,
                {"backend.context"},
            ),
            (
                "from . import child",
                "backend.providers",
                True,
                {"backend.providers.child"},
            ),
            (
                "def load():\n    from .context import symbol",
                "backend.providers.adapter",
                False,
                {"backend.providers.context"},
            ),
            (
                "from .new_module import symbol",
                "backend.providers.adapter",
                False,
                {"backend.providers.new_module"},
            ),
        )
        for text, source, is_package, expected in cases:
            with self.subTest(text=text, source=source):
                self.assertEqual(
                    expected,
                    _imports(
                        source,
                        ast.parse(text),
                        modules,
                        is_package=is_package,
                    ),
                )
        self.assertEqual(
            "backend.providers",
            _module_name(
                REPOSITORY_ROOT / "backend/providers/__init__.py", REPOSITORY_ROOT
            ),
        )

    def test_nested_layers_and_dynamic_server_access_are_detected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                "backend/providers/nested/adapter.py": "def load():\n    from ...coach.context import Service\n",
                "backend/http_api/nested/route.py": "from backend.providers.openai import Client\n",
                "backend/planning/nested/service.py": "from backend.http_api.auth import Service\n",
                "backend/db/nested/store.py": "from backend.coach.context import Service\n",
                "backend/runtime/nested/worker.py": "from backend.db.manager import Store\n",
            }
            for relative, text in sources.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                {
                    ("backend/providers/nested/adapter.py", "backend.coach.context"),
                    ("backend/http_api/nested/route.py", "backend.providers.openai"),
                    ("backend/planning/nested/service.py", "backend.http_api.auth"),
                    ("backend/db/nested/store.py", "backend.coach.context"),
                    ("backend/runtime/nested/worker.py", "backend.db.manager"),
                },
                _import_violations(root),
            )
        path = BACKEND_ROOT / "providers/synthetic.py"
        for text in (
            "import sys\nstate = sys.modules['server']\nstate.DB",
            "import importlib as loader\ndef load():\n    return loader.import_module('server')",
        ):
            with self.subTest(text=text):
                self.assertTrue(_server_import_violations(path, ast.parse(text)))

    def test_sql_candidates_detect_arbitrary_receivers_and_preserve_service_dispatch(
        self,
    ) -> None:
        relative = "backend/http_api/nested/synthetic.py"
        tree = ast.parse(
            "class Route:\n"
            "    def handle(self, service, payload, query):\n"
            "        service.execute(payload)\n"
            "        self.connection.execute(query)\n"
            "        unknown.execute(query)\n"
            "        self.connection.cursor().executemany(query, [])\n"
            "        unknown.executescript(query)\n"
        )
        service_key = (relative, "Route.handle", "service.execute")
        calls = _execute_calls(tree, relative)
        candidates = _sql_candidates(calls, {service_key: 1})
        self.assertNotIn(service_key, candidates)
        self.assertEqual(
            {
                (relative, "Route.handle", "self.connection.execute"): 1,
                (relative, "Route.handle", "unknown.execute"): 1,
                (relative, "Route.handle", "self.connection.cursor().executemany"): 1,
                (relative, "Route.handle", "unknown.executescript"): 1,
            },
            dict(candidates),
        )
        self.assertEqual(calls, _sql_candidates(calls, {}))
        self.assertEqual(
            1,
            _sql_candidates(calls + Counter({service_key: 1}), {service_key: 1})[
                service_key
            ],
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(ast.unparse(tree), encoding="utf-8")
            self.assertEqual(calls, _http_execute_calls(root))

    def test_canonical_package_imports_only_stdlib_and_itself(self) -> None:
        self.assertEqual(
            [],
            _canonical_stdlib_violations(BACKEND_ROOT / "canonical"),
        )

    def test_canonical_stdlib_guard_rejects_outside_imports(self) -> None:
        with TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "backend" / "canonical"
            package_root.mkdir(parents=True)
            (package_root / "ok.py").write_text(
                "import json\n"
                "from . import vocabulary\n"
                "from .vocabulary import Sport\n"
                "from backend.canonical.vocabulary import Sport\n",
                encoding="utf-8",
            )
            (package_root / "bad.py").write_text(
                "from backend.coach import service\n"
                "from ..coach import service2\n"
                "import requests\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [
                    "canonical/bad.py: ..coach",
                    "canonical/bad.py: backend.coach",
                    "canonical/bad.py: requests",
                ],
                _canonical_stdlib_violations(package_root),
            )

    def test_canonical_layer_is_leaf_and_permitted_by_every_layer_key(self) -> None:
        self.assertEqual("canonical", _layer("backend.canonical.records"))
        self.assertEqual({CANONICAL_PACKAGE}, PERMITTED_IMPORTS_BY_LAYER["canonical"])
        for layer, permitted in PERMITTED_IMPORTS_BY_LAYER.items():
            with self.subTest(layer=layer):
                self.assertIn(CANONICAL_PACKAGE, permitted)

    def test_canonical_import_direction_is_enforced_for_sample_layers(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                "backend/canonical/records.py": (
                    "import json\n"
                    "from backend.canonical.vocabulary import Sport\n"
                    "from backend.db import manager\n"
                ),
                "backend/canonical/vocabulary.py": "from enum import StrEnum\n",
                "backend/providers/adapter.py": (
                    "from backend.canonical.records import Observation\n"
                ),
                "backend/coach/service.py": "from backend.canonical import records\n",
            }
            for relative, text in sources.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                {("backend/canonical/records.py", "backend.db")},
                _import_violations(root),
            )

    def test_http_sql_execute_sites_match_pending_baseline(self) -> None:
        calls = _http_execute_calls(REPOSITORY_ROOT)
        self.assertEqual(
            Counter(DOMAIN_EXECUTE_CALLS),
            Counter({key: calls[key] for key in DOMAIN_EXECUTE_CALLS}),
            "Review changes to the three non-SQL service dispatches explicitly.",
        )
        self.assertEqual(
            Counter(),
            _sql_candidates(calls, DOMAIN_EXECUTE_CALLS),
            "HTTP handlers must delegate database calls to repositories.",
        )
        self.assertEqual([], _http_sql_literals(REPOSITORY_ROOT))


if __name__ == "__main__":
    unittest.main()
