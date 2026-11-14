"""Run the SonarQube CLI on a change and print counts and locations only.

    python scripts/sonar_check.py [--base origin/develop]
    python scripts/sonar_check.py --pr 123

Prints counts, then one `issue <rule> <file>:<line>` line per issue. Messages,
matched text and every other payload field are never printed. A forbidden
global error (the server-side agentic analysis is not available) is printed as
a `limit` line: that part was not analyzed and is not a pass.
Exit 0: no issues; 1: issues, failures or an unusable result; 2: bad input or
the Sonar CLI is missing; 3: no issues, but part of the analysis was not run
(the `limit` line).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from gh_cli import positive_int

SETUP_HINT = (
    "Sonar CLI not found. Install it from https://sonarsource.com/sonarqube/cli, "
    "put it on PATH, and run `sonar auth login`."
)
TIMEOUT = 900  # seconds; bounds any hung sonar CLI call
SAFE_RULE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
SAFE_FILE = re.compile(r"[\w./\\@+ -]{1,200}")
# Top-level keys that are not issue sections.
# `messages` holds CLI notices whose text is never printed.
NOT_SECTIONS = frozenset({"failures", "errors", "globalError", "paging", "messages"})


def find_sonar() -> str | None:
    found = shutil.which("sonar")
    if found:
        return found
    name = "sonar.exe" if os.name == "nt" else "sonar"
    roots = [
        Path.home() / ".sonar" / "sonarqube-cli" / "bin",
        Path.home() / ".local" / "bin",
    ]
    if os.environ.get("LOCALAPPDATA"):
        roots.insert(0, Path(os.environ["LOCALAPPDATA"]) / "sonarqube-cli" / "bin")
    return next((str(root / name) for root in roots if (root / name).is_file()), None)


def run_sonar(sonar: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI; a non-zero exit is data, since it may still print JSON."""
    return subprocess.run(
        [sonar, *args],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
    )


def parse_json(text: str) -> Any:
    """The first JSON value in the output (a banner may precede it), or None."""
    decoder = json.JSONDecoder()
    starts = [i for i, char in enumerate(text) if char in "{["][:20]
    for start in starts:
        try:
            return decoder.raw_decode(text, start)[0]
        except json.JSONDecodeError:
            continue
    return None


def issue_list(value: Any) -> list[dict] | None:
    """The issue dicts of a section value, or None when it is not a section.

    `sonar analyze` nests sections such as `secrets` and `agentic`; one without
    an `issues` list but with a `summary` is a section with no listed issue.
    """
    if isinstance(value, dict):
        if "issues" not in value and isinstance(value.get("summary"), dict):
            return []
        value = value.get("issues")
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    return None


def sections_of(data: Any) -> dict[str, list[dict]]:
    if isinstance(data, list):
        data = {"issues": data}
    if not isinstance(data, dict):
        return {}
    found: dict[str, list[dict]] = {}
    for key, value in data.items():
        issues = None if key in NOT_SECTIONS else issue_list(value)
        if issues is not None:
            found[str(key)] = issues
    return found


def count_of(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return len(value) if isinstance(value, list) else 0


def parts(data: Any) -> list[dict]:
    """The top level and each nested section, where failures and errors live."""
    if not isinstance(data, dict):
        return []
    return [data, *(v for v in data.values() if isinstance(v, dict))]


def failures_of(data: Any) -> int:
    return sum(
        count_of(part.get("failures")) + count_of(part.get("errors"))
        for part in parts(data)
    )


def global_error_kind(data: Any) -> str | None:
    for part in parts(data):
        error = part.get("globalError")
        kind = error.get("kind") if isinstance(error, dict) else None
        if isinstance(kind, str) and SAFE_RULE.fullmatch(kind):
            return kind
    return None


def safe(value: Any, pattern: re.Pattern[str]) -> str:
    return value if isinstance(value, str) and pattern.fullmatch(value) else "?"


def location(issue: dict) -> str:
    """`rule file:line` from known fields only; unsafe values print as `?`."""
    rule = safe(
        issue.get("ruleKey") or issue.get("rule") or issue.get("key"), SAFE_RULE
    )
    path = issue.get("file") or issue.get("filePath") or issue.get("path")
    if not path and isinstance(issue.get("component"), str):
        path = issue["component"].split(":", 1)[-1]  # "<project key>:<path>"
    line = issue.get("line") or issue.get("startLine")
    if line is None and isinstance(issue.get("textRange"), dict):
        line = issue["textRange"].get("startLine")
    line_text = str(line) if isinstance(line, int) and line > 0 else "?"
    return f"{rule} {safe(path, SAFE_FILE)}:{line_text}"


def report(label: str, data: Any) -> int:
    sections = sections_of(data)
    issues = sum(len(items) for items in sections.values())
    failures = failures_of(data)
    print(f"{label}: issues {issues}, failures {failures}")
    for name, items in sections.items():
        print(f"section {name}: {len(items)}")
    if global_error_kind(data) == "forbidden":
        print("limit: agentic (Vortex) analysis forbidden; not analyzed, not a pass")
    for items in sections.values():
        for issue in items:
            print(f"issue {location(issue)}")
    if issues or failures:
        return 1
    return 3 if global_error_kind(data) == "forbidden" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument("--pr", type=positive_int, help="list a pull request's issues")
    args = parser.parse_args(argv)
    sonar = find_sonar()
    if not sonar:
        print(f"error: {SETUP_HINT}", file=sys.stderr)
        return 2
    if args.pr:
        command = ["list", "issues", "--pull-request", str(args.pr), "--format", "json"]
        label = f"sonar PR {args.pr}"
    else:
        command = ["analyze", "--base", args.base, "--format", "json"]
        label = f"sonar analyze vs {args.base}"
    try:
        done = run_sonar(sonar, *command)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAILED {label}: {type(exc).__name__}")
        return 1
    data = parse_json(done.stdout or "")
    if data is None:
        print(f"FAILED {label}: no JSON result (exit {done.returncode})")
        return 1
    if args.pr and isinstance(data, dict):
        # The issue list also carries `components` and `users`: not issues.
        data = {"issues": data.get("issues") or []}
    code = report(label, data)
    if code == 0 and done.returncode != 0 and global_error_kind(data) != "forbidden":
        print(f"FAILED {label}: exit {done.returncode} without a listed issue")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
