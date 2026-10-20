"""Check every repository Python file against explicit diagnostic debt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/quality_baseline.json"
REQUIREMENTS = ROOT / "requirements-dev.txt"
TOOLS = ("ruff", "mypy")
# Line and column are reported for humans but are not debt identity, so an
# unrelated edit that moves a known diagnostic does not fail the ratchet.
IDENTITY_FIELDS = ("tool", "path", "code", "message_sha256")
NON_SOURCE_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "data",
    ".mypy_cache",
    ".ruff_cache",
}


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


def run(command: list[str], root: Path, allowed: tuple[int, ...] = (0, 1)) -> str:
    result = subprocess.run(
        command, cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode not in allowed:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"{command[0]} failed with exit {result.returncode}{suffix}")
    if result.returncode == 1 and not result.stdout.strip():
        raise RuntimeError(f"{command[0]} failed without diagnostic output")
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


def collect(root: Path) -> tuple[dict[str, str], list[dict]]:
    files = source_files(root)
    if not files:
        raise RuntimeError("No Python source files discovered")
    versions = {}
    for tool in TOOLS:
        output = run([tool, "--version"], root, (0,))
        match = re.search(r"\b\d+\.\d+\.\d+\b", output)
        if not match:
            raise RuntimeError(f"Cannot identify {tool} version")
        versions[tool] = match.group()

    ruff_output = run(
        [
            "ruff",
            "check",
            "--no-cache",
            "--config",
            "pyproject.toml",
            "--output-format=json",
            *files,
        ],
        root,
    )
    diagnostics = [diagnostic("ruff", item, root) for item in json.loads(ruff_output)]
    with tempfile.TemporaryDirectory(prefix="quality-mypy-") as cache:
        mypy_output = run(
            [
                "mypy",
                "--config-file",
                "pyproject.toml",
                "--no-incremental",
                "--cache-dir",
                cache,
                "--no-error-summary",
                "--output=json",
                *files,
            ],
            root,
        )
    for line in mypy_output.splitlines():
        item = json.loads(line)
        if item["severity"] == "error":
            diagnostics.append(diagnostic("mypy", item, root))

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


def check(baseline: dict, versions: dict[str, str], diagnostics: list[dict]) -> int:
    if baseline["schema"] != 1:
        raise RuntimeError("Quality baseline schema does not match")
    if baseline["versions"] != versions:
        raise RuntimeError(
            f"Quality baseline tool versions {baseline['versions']} do not match "
            f"installed {versions}. Run `python tools/quality_baseline.py "
            "--align-versions` and commit tests/fixtures/quality_baseline.json."
        )
    if any(
        item.get("tool") not in {"ruff", "mypy"}
        for item in [*baseline["diagnostics"], *diagnostics]
    ):
        raise RuntimeError("Quality baseline supports Ruff and mypy diagnostics only")
    added, obsolete = compare(baseline["diagnostics"], diagnostics)
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
            "`python tools/quality_baseline.py --snapshot --base <commit>` and "
            "update tests/fixtures/quality_baseline.json."
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
    parser.add_argument("--baseline-file", type=Path, default=BASELINE)
    parser.add_argument("--requirements", type=Path, default=REQUIREMENTS)
    args = parser.parse_args()
    if args.align_versions:
        aligned = aligned_baseline(
            args.baseline_file.read_text(encoding="utf-8"),
            args.requirements.read_text(encoding="utf-8"),
        )
        if aligned is not None:
            args.baseline_file.write_text(aligned, encoding="utf-8")
        print("aligned" if aligned is not None else "unchanged")
        return 0
    versions, diagnostics = collect(ROOT)
    if args.snapshot:
        if not args.base or not re.fullmatch(r"[0-9a-f]{40}", args.base):
            parser.error("--snapshot requires an immutable --base SHA")
        current = json.loads(BASELINE.read_text(encoding="utf-8"))
        print(
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
        )
        return 0
    return check(
        json.loads(BASELINE.read_text(encoding="utf-8")), versions, diagnostics
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        print(f"Quality check failed: {error}", file=sys.stderr)
        sys.exit(2)
