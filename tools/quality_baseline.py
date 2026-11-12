"""Check every repository Python file against explicit diagnostic debt."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/quality_baseline.json"
REQUIREMENTS = ROOT / "requirements-dev.txt"
TOOLS = ("ruff", "mypy")
# The cognitive counter is this module's own code and has no pinned version, so
# it stays out of TOOLS (version recording and alignment) but is accepted debt.
COGNITIVE = "cognitive"
COGNITIVE_CODE = "S3776"
COGNITIVE_LIMIT = 15
# Line and column are reported for humans but are not debt identity, so an
# unrelated edit that moves a known diagnostic does not fail the ratchet.
IDENTITY_FIELDS = ("tool", "path", "code", "message_sha256")
NON_SOURCE_DIRECTORIES = {
    ".git",
    ".graphify-local",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "data",
    ".mypy_cache",
    ".ruff_cache",
}
# Windows limits a command line to 32767 characters, which the repository's
# file list exceeds: Ruff checks files independently, so it runs in batches
# within this path budget, while mypy reads the complete list from an argument
# file to keep cross-module analysis.
COMMAND_LINE_PATH_BUDGET = 30000
# Sonar's JavaScript rules S3776 (cognitive complexity) and S3358 (nested
# ternary) through eslint-plugin-sonarjs. CI's quality job installs no Node
# packages, so there the step reports that it was skipped; the pre-push hook
# points PACECRAFT_NODE_MODULES at the clone because its HEAD export has none.
ESLINT_CONFIG = ROOT / "tools/eslint.sonar.config.mjs"


def tool_command(tool: str) -> list[str]:
    """Run the tool from this interpreter, where worktree preparation installs it."""
    return [sys.executable, "-m", tool]


def path_batches(files: list[str]) -> list[list[str]]:
    batches: list[list[str]] = [[]]
    size = 0
    for path in files:
        # A separator and possible quotes accompany each path.
        length = len(path) + 3
        if batches[-1] and size + length > COMMAND_LINE_PATH_BUDGET:
            batches.append([])
            size = 0
        batches[-1].append(path)
        size += length
    return batches


def source_files(root: Path) -> list[str]:
    files: list[str] = []
    for directory, children, filenames in os.walk(root):
        children[:] = [
            name
            for name in children
            if name != "__pycache__"
            and not (Path(directory) == root and name in NON_SOURCE_DIRECTORIES)
        ]
        files.extend(
            (Path(directory) / name).relative_to(root).as_posix()
            for name in filenames
            if name.endswith((".py", ".pyi"))
        )
    return sorted(files)


def tool_name(command: list[str]) -> str:
    return command[2] if command[1:2] == ["-m"] else command[0]


def run(command: list[str], root: Path, allowed: tuple[int, ...] = (0, 1)) -> str:
    result = subprocess.run(
        command, cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode not in allowed:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(
            f"{tool_name(command)} failed with exit {result.returncode}{suffix}"
        )
    if result.returncode == 1 and not result.stdout.strip():
        raise RuntimeError(f"{tool_name(command)} failed without diagnostic output")
    return result.stdout


def diagnostic(tool: str, item: dict, root: Path) -> dict:
    path = Path(item["filename"] if tool == "ruff" else item["file"])
    if not path.is_absolute():
        path = root / path
    location = item["location"] if tool == "ruff" else item
    return {
        "tool": tool,
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "line": location["row"] if tool == "ruff" else location["line"],
        "column": location["column"],
        "code": item["code"],
        "message_sha256": hashlib.sha256(item["message"].encode()).hexdigest(),
    }


# Structures that count 1 plus nesting; their listed fields sit at their own
# level and everything else (the body, handlers, cases) one level deeper.
_COGNITIVE_HEADS = {
    ast.For: ("target", "iter"),
    ast.AsyncFor: ("target", "iter"),
    ast.While: ("test",),
    ast.ExceptHandler: ("type",),
    ast.Match: ("subject",),
}


def _cognitive_score(node: ast.AST, nesting: int, operator: type | None = None) -> int:
    """Score one node and its descendants; `operator` is a boolean parent's kind."""
    if isinstance(node, ast.BoolOp):
        # Like operators in one chain, even across parentheses, count once.
        own = 0 if operator is type(node.op) else 1
        return own + sum(
            _cognitive_score(value, nesting, type(node.op)) for value in node.values
        )
    if isinstance(node, ast.If):
        return _if_score(node, nesting, 1 + nesting)
    heads = _COGNITIVE_HEADS.get(type(node))
    if heads is not None:
        return (
            1
            + nesting
            + sum(
                _cognitive_score(child, nesting + (field not in heads))
                for field, value in ast.iter_fields(node)
                for child in (value if isinstance(value, list) else [value])
                if isinstance(child, ast.AST)
            )
        )
    own = 1 + nesting if isinstance(node, ast.IfExp) else 0
    if isinstance(
        node, ast.IfExp | ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef
    ):
        nesting += 1
    return own + sum(
        _cognitive_score(child, nesting) for child in ast.iter_child_nodes(node)
    )


def _if_score(node: ast.If, nesting: int, increment: int) -> int:
    total = increment + _cognitive_score(node.test, nesting)
    total += sum(_cognitive_score(item, nesting + 1) for item in node.body)
    rest = node.orelse
    # `elif` is an If whose keyword starts at the column of its parent's `if`.
    if (
        len(rest) == 1
        and isinstance(rest[0], ast.If)
        and rest[0].col_offset == node.col_offset
    ):
        return total + _if_score(rest[0], nesting, 1)
    if rest:
        total += 1 + sum(_cognitive_score(item, nesting + 1) for item in rest)
    return total


def cognitive_complexity(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return SonarQube's python:S3776 cognitive complexity of a function body.

    Structures count 1 plus their nesting level: if, ternary, for, while, except
    and match. `elif` and `else` count 1 without nesting; each chain of like
    `and`/`or` operators counts 1; lambdas and nested functions raise the nesting
    of their content, which belongs to the enclosing function. Simplifications:
    recursion, comprehensions, `else` of loops and try, and `try`/`with` blocks
    count nothing, and the decorators and defaults of the measured function are
    not scored.
    """
    return sum(_cognitive_score(statement, 0) for statement in function.body)


def _functions(node: ast.AST, prefix: str = ""):
    """Yield (qualified name, function) for every outermost function and method."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield prefix + child.name, child
        elif isinstance(child, ast.ClassDef):
            yield from _functions(child, f"{prefix}{child.name}.")
        else:
            yield from _functions(child, prefix)


def cognitive_diagnostics(root: Path, files: list[str]) -> list[dict]:
    """Report each function above the limit by name, never by score, so the
    baseline identity survives the score changing."""
    diagnostics = []
    for path in files:
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8"), path)
        except SyntaxError as error:
            raise RuntimeError(f"Cannot parse {path} for complexity") from error
        for name, function in _functions(tree):
            if cognitive_complexity(function) > COGNITIVE_LIMIT:
                message = f"Cognitive complexity of {name} is above {COGNITIVE_LIMIT}"
                diagnostics.append(
                    {
                        "tool": COGNITIVE,
                        "path": path,
                        "line": function.lineno,
                        "column": function.col_offset + 1,
                        "code": COGNITIVE_CODE,
                        "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                    }
                )
    return diagnostics


def eslint_script() -> Path | None:
    modules = os.environ.get("PACECRAFT_NODE_MODULES")
    script = Path(modules or ROOT / "node_modules") / "eslint/bin/eslint.js"
    return script if script.is_file() and shutil.which("node") else None


def javascript_diagnostics(root: Path) -> list[dict] | None:
    """Sonar's complexity and nested-ternary rules for public/*.js; None if skipped."""
    script = eslint_script()
    if script is None:
        print("Quality ratchet: ESLint not installed (npm ci); skipped public/*.js")
        return None
    files = sorted(
        path.relative_to(root).as_posix() for path in (root / "public").glob("*.js")
    )
    if not files:
        return []
    output = run(
        [
            "node",
            str(script),
            "--no-config-lookup",
            "--config",
            str(ESLINT_CONFIG),
            "--format",
            "json",
            *files,
        ],
        root,
    )
    diagnostics = []
    for result in json.loads(output):
        path = Path(result["filePath"]).resolve().relative_to(root.resolve()).as_posix()
        lines = (root / path).read_text(encoding="utf-8").splitlines()
        for item in result["messages"]:
            if not item.get("ruleId"):
                raise RuntimeError(f"ESLint could not check {path}: {item['message']}")
            # Sonar suppresses an issue on a line marked NOSONAR.
            if "NOSONAR" in lines[item["line"] - 1]:
                continue
            # The score changes with the code and is not part of the identity.
            message = re.sub(r"\b\d+\b", "N", item["message"])
            diagnostics.append(
                {
                    "tool": "eslint",
                    "path": path,
                    "line": item["line"],
                    "column": item["column"],
                    "code": item["ruleId"],
                    "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                }
            )
    return diagnostics


def collect(root: Path) -> tuple[dict[str, str], list[dict]]:
    files = source_files(root)
    if not files:
        raise RuntimeError("No Python source files discovered")
    versions = {}
    for tool in TOOLS:
        output = run([*tool_command(tool), "--version"], root, (0,))
        match = re.search(r"\b\d+\.\d+\.\d+\b", output)
        if not match:
            raise RuntimeError(f"Cannot identify {tool} version")
        versions[tool] = match.group()

    diagnostics: list[dict] = []
    for batch in path_batches(files):
        ruff_output = run(
            [
                *tool_command("ruff"),
                "check",
                "--no-cache",
                "--config",
                "pyproject.toml",
                "--output-format=json",
                *batch,
            ],
            root,
        )
        diagnostics.extend(
            diagnostic("ruff", item, root) for item in json.loads(ruff_output)
        )
    with tempfile.TemporaryDirectory(prefix="quality-mypy-") as cache:
        file_list = Path(cache) / "files.txt"
        file_list.write_text("\n".join(files) + "\n", encoding="utf-8")
        mypy_output = run(
            [
                *tool_command("mypy"),
                "--config-file",
                "pyproject.toml",
                "--no-incremental",
                "--cache-dir",
                cache,
                "--no-error-summary",
                "--output=json",
                f"@{file_list}",
            ],
            root,
        )
    for line in mypy_output.splitlines():
        item = json.loads(line)
        if item["severity"] == "error":
            diagnostics.append(diagnostic("mypy", item, root))
    diagnostics.extend(cognitive_diagnostics(root, files))
    diagnostics.extend(javascript_diagnostics(root) or [])

    return versions, sorted(
        diagnostics, key=lambda item: json.dumps(item, sort_keys=True)
    )


def identity(item: dict) -> dict:
    return {field: item[field] for field in IDENTITY_FIELDS}


def identity_key(item: dict) -> str:
    return json.dumps(identity(item), sort_keys=True)


def compare(expected: list[dict], actual: list[dict]) -> tuple[list[dict], list[dict]]:
    remaining = Counter(identity_key(item) for item in expected)
    added: list[dict] = []
    for item in actual:
        key = identity_key(item)
        if remaining[key]:
            remaining[key] -= 1
        else:
            added.append(item)
    obsolete = [
        json.loads(key) for key, count in remaining.items() for _ in range(count)
    ]
    return added, obsolete


def pinned_versions(requirements: str) -> dict[str, str]:
    versions = {}
    for tool in TOOLS:
        match = re.search(
            rf"^{tool}==(\d+\.\d+\.\d+)(?![\w.])", requirements, flags=re.MULTILINE
        )
        if not match:
            raise RuntimeError(f"Cannot identify the pinned {tool} version")
        versions[tool] = match.group(1)
    return versions


def aligned_baseline(baseline_text: str, requirements: str) -> str | None:
    """Return the baseline with pinned tool versions, or None when they already match.

    Only the version record changes; CI still proves the diagnostics under the
    new tools, so a bump that adds findings keeps failing for a person to fix.
    """
    baseline = json.loads(baseline_text)
    if baseline.get("schema") != 1 or set(baseline.get("versions", {})) != set(TOOLS):
        raise RuntimeError("Quality baseline schema or tools are not supported")
    versions = pinned_versions(requirements)
    if baseline["versions"] == versions:
        return None
    baseline["versions"] = versions
    return json.dumps(baseline, indent=2) + "\n"


def check(
    baseline: dict,
    versions: dict[str, str],
    diagnostics: list[dict],
    skipped: tuple[str, ...] = (),
) -> int:
    if baseline["schema"] != 1:
        raise RuntimeError("Quality baseline schema does not match")
    if baseline["versions"] != versions:
        raise RuntimeError(
            f"Quality baseline tool versions {baseline['versions']} do not match "
            f"installed {versions}. Run `python tools/quality_baseline.py "
            "--align-versions` and commit tests/fixtures/quality_baseline.json."
        )
    if any(
        item.get("tool") not in {*TOOLS, COGNITIVE, "eslint"}
        for item in [*baseline["diagnostics"], *diagnostics]
    ):
        raise RuntimeError(
            "Quality baseline supports Ruff, mypy, cognitive complexity and "
            "ESLint diagnostics only"
        )
    expected = [item for item in baseline["diagnostics"] if item["tool"] not in skipped]
    added, obsolete = compare(expected, diagnostics)
    for label, items in (("NEW", added), ("OBSOLETE", obsolete)):
        for item in items:
            location = (
                f"{item['path']}:{item['line']}" if "line" in item else item["path"]
            )
            print(f"{label} {item['tool']} {location} {item['code']}")
    print(
        f"Quality ratchet: {len(diagnostics)} existing, {len(added)} new, {len(obsolete)} obsolete"
    )
    if obsolete:
        print(
            "Obsolete baseline entries must be removed. Regenerate with "
            "`python tools/quality_baseline.py --snapshot --base <commit>`, which "
            "rewrites tests/fixtures/quality_baseline.json."
        )
    return 1 if added or obsolete else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--base")
    parser.add_argument(
        "--align-versions",
        action="store_true",
        help="record the requirements-dev.txt tool pins without running the tools",
    )
    args = parser.parse_args()
    if args.align_versions:
        aligned = aligned_baseline(
            BASELINE.read_text(encoding="utf-8"),
            REQUIREMENTS.read_text(encoding="utf-8"),
        )
        if aligned is not None:
            BASELINE.write_text(aligned, encoding="utf-8")
        print("aligned" if aligned is not None else "unchanged")
        return 0
    versions, diagnostics = collect(ROOT)
    if args.snapshot:
        if not args.base or not re.fullmatch(r"[0-9a-f]{40}", args.base):
            parser.error("--snapshot requires an immutable --base SHA")
        current = json.loads(BASELINE.read_text(encoding="utf-8"))
        BASELINE.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "base": args.base,
                    "versions": versions,
                    "diagnostics": [
                        identity(item) for item in sorted(diagnostics, key=identity_key)
                    ],
                    "coverage_evidence": current.get("coverage_evidence"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Quality ratchet: wrote {BASELINE.relative_to(ROOT).as_posix()}")
        return 0
    return check(
        json.loads(BASELINE.read_text(encoding="utf-8")),
        versions,
        diagnostics,
        () if eslint_script() else ("eslint",),
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        print(f"Quality check failed: {error}", file=sys.stderr)
        sys.exit(2)
