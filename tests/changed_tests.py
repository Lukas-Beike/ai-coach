"""Select the Python test modules a local change can affect.

Local runs use this to skip unaffected modules; CI still runs every shard. A test
module is selected when its own file changed, when it transitively imports a
changed repository module, or when a string literal in it (or in a test support
module it imports) names the changed path, a parent directory of it, its file
name, or its dotted module name. The literal rule catches source-scanning
contract tests and ``mock.patch("backend...")`` targets that imports miss.
A bare top-level directory name only counts in a module that iterates
directories. A module whose literals name a changed data file under backend/
counts as changed. Imports reached only through ``server.py`` count only when
``server.py`` or a module under SERVER_WIRED_PATHS changed: app-wide tests then
stay in CI unless they import the changed module another way. Changes under
FULL_SUITE_PATHS, or a source that cannot be parsed, select the whole suite
(returned as ``None``).
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# Paths whose change affects most of the suite or its harness. A trailing slash
# marks a directory prefix; anything else is an exact path or a file prefix.
FULL_SUITE_PATHS = (
    "backend/canonical/",
    "backend/db/",
    "tests/run_tests.py",
    "tests/changed_tests.py",
    "tests/support.py",
    "tests/server_test_support.py",
    "tests/fixtures/",
    "requirements",
    "Dockerfile",
    "pyproject.toml",
)
# Too generic to identify one file by name alone.
GENERIC_NAMES = frozenset({"__init__.py", "AGENTS.md", "SKILL.md", "README.md"})
SOURCE_GLOBS = (
    "server.py",
    "backend/**/*.py",
    "tests/*.py",
    "scripts/*.py",
    "tools/*.py",
)
# Changes here are exercised mostly through the app that server.py assembles.
SERVER_WIRED_PATHS = ("server.py", "backend/http_api/", "backend/runtime/")
SCAN_CALLS = frozenset({"glob", "rglob", "iterdir", "walk"})
COMPOSITION_ROOT = "server"


def _git(*args: str, root: Path) -> list[str]:
    output = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


def changed_paths(base: str, root: Path = ROOT) -> list[str]:
    """Committed, staged, unstaged, and untracked paths since the merge base."""
    merge_base = _git("merge-base", base, "HEAD", root=root)[0]
    paths = _git("diff", "--name-only", "--no-renames", merge_base, root=root)
    paths += _git("ls-files", "--others", "--exclude-standard", root=root)
    return sorted(set(paths))


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if parts[0] == "tests":
        parts.pop(0)  # tests run with tests/ on sys.path
    return ".".join(parts)


class _Source:
    def __init__(self, path: Path, root: Path):
        self.module = _module_name(path, root)
        self.path = path.relative_to(root).as_posix()
        self.package = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        self.imports: set[str] = set()
        self.literals: set[str] = set()
        self.scans = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute(node)
                self.imports.add(base)
                self.imports.update(f"{base}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Attribute) and node.attr in SCAN_CALLS:
                self.scans = True
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literal = node.value.strip().replace("\\", "/").removeprefix("./")
                if literal and "\n" not in literal and len(literal) < 200:
                    self.literals.add(literal.strip("/"))

    def _absolute(self, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        parts = self.module.split(".")
        keep = len(parts) - node.level + (1 if self.package else 0)
        return ".".join(parts[: max(keep, 0)] + ([node.module] if node.module else []))


def _load_sources(root: Path) -> dict[str, _Source]:
    sources = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            source = _Source(path, root)
            sources[source.module] = source
    # `from tests import run_tests` names the same module as `import run_tests`,
    # and tests that put scripts/ or tools/ on sys.path import them bare.
    for name in list(sources):
        if name.startswith("test") or "." not in name:
            sources.setdefault(f"tests.{name}", sources[name])
        if name.startswith(("scripts.", "tools.")):
            sources.setdefault(name.partition(".")[2], sources[name])
    return sources


def _resolve(name: str, sources: dict[str, _Source]) -> list[str]:
    """The module ``name`` loads plus its parent packages, which import runs too."""
    while name and name not in sources:
        name = name.rpartition(".")[0]
    resolved = []
    while name:
        if name in sources:
            resolved.append(sources[name].module)
        name = name.rpartition(".")[0]
    return resolved


def _closure(
    module: str, sources: dict[str, _Source], through_server: bool
) -> set[str]:
    seen: set[str] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current == COMPOSITION_ROOT and not through_server:
            continue
        for name in sources[current].imports:
            for resolved in _resolve(name, sources):
                if resolved not in seen:
                    seen.add(resolved)
                    pending.append(resolved)
    return seen


def _needles(path: str) -> tuple[set[str], set[str]]:
    """Literals that name ``path``: exact values, and dotted-module prefixes."""
    parts = path.split("/")
    exact = {"/".join(parts[:index]) for index in range(1, len(parts) + 1)}
    exact |= {"/".join(parts[index:]) for index in range(1, len(parts))}
    if parts[-1] in GENERIC_NAMES and len(parts) > 1:
        exact.discard(parts[-1])
    dotted = set()
    if path.endswith(".py"):
        module = ".".join(Path(path).with_suffix("").parts)
        dotted.add(module.removesuffix(".__init__").removeprefix("tests."))
    return exact, dotted


def _names(source: _Source, literal: str, exact: set[str], dotted: set[str]) -> bool:
    if "/" not in literal and "." not in literal and not source.scans:
        return False  # a bare directory name names nothing without a scan
    return literal in exact or any(
        literal == module or literal.startswith(module + ".") for module in dotted
    )


def full_suite_reason(paths: list[str]) -> str | None:
    for path in paths:
        for prefix in FULL_SUITE_PATHS:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                return f"{path} matches full-suite path {prefix}"
    return None


def select_modules(
    paths: list[str], root: Path = ROOT
) -> tuple[dict[str, str] | None, str]:
    """Return {test module: reason}, or None and the reason to run everything."""
    reason = full_suite_reason(paths)
    if reason:
        return None, reason
    try:
        sources = _load_sources(root)
    except SyntaxError as error:
        return None, f"cannot parse {error.filename}"
    # Deleted or renamed modules count too: a lazy import of one still breaks.
    changed_modules = {
        _module_name(root / path, root): path for path in paths if path.endswith(".py")
    }
    needles = {path: _needles(path) for path in paths}
    for path, (exact, dotted) in needles.items():
        if path.endswith(".py") or not path.startswith("backend/"):
            continue
        for source in sources.values():
            if not source.path.startswith("tests/") and any(
                _names(source, x, exact, dotted) for x in source.literals
            ):
                changed_modules.setdefault(source.module, path)
    gone = {m for m in changed_modules if m not in sources}
    through_server = any(
        path == prefix or path.startswith(prefix)
        for path in paths
        for prefix in SERVER_WIRED_PATHS
    )
    selected: dict[str, str] = {}
    for module, source in sources.items():
        if module != source.module or not Path(source.path).name.startswith("test_"):
            continue
        if source.path in paths:
            selected[module] = f"changed {source.path}"
            continue
        reach = _closure(module, sources, through_server)
        hit = next(
            (changed_modules[m] for m in sorted(reach) if m in changed_modules), None
        )
        if not hit and gone:
            names = source.imports.union(*(sources[m].imports for m in reach))
            hit = next(
                (
                    changed_modules[m]
                    for m in sorted(gone)
                    if any(n == m or n.startswith(m + ".") for n in names)
                ),
                None,
            )
        if hit:
            selected[module] = f"imports {hit}"
            continue
        texts = [source] + [
            sources[m] for m in sorted(reach) if sources[m].path.startswith("tests/")
        ]
        for path, (exact, dotted) in needles.items():
            owner = next(
                (
                    s
                    for s in texts
                    if any(_names(s, x, exact, dotted) for x in s.literals)
                ),
                None,
            )
            if owner:
                selected[module] = f"{owner.path} names {path}"
                break
    return selected, f"{len(selected)} modules affected by {len(paths)} paths"
