"""Run the local checks for a change: affected tests, compile, quality, JS tests.

    python scripts/check_changed.py [--base origin/develop] [--js]

Every step runs even after a failure. One line per step; for each failed step its
unittest FAIL/ERROR lines, the last lines of its output, and the path of a
temporary file with its full output. Node tests run with --js or when the diff against the
base touches a .js, .cjs or .mjs file. Exit 0: all passed; 1: a step failed;
2: bad base ref or a tool is missing.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from gh_cli import CliError, git

ROOT = Path(__file__).resolve().parents[1]
JS_SUFFIXES = (".js", ".cjs", ".mjs")
TAIL_LINES = 20
# The unittest lines that name a failed test; they sit far above the tail.
FAILED_TEST = re.compile(r"^(?:FAIL|ERROR): ")


class MissingTool(Exception):
    """A step's program is not installed."""


def run_step(argv: list[str]) -> tuple[bool, float, str]:
    """Run one step; return (passed, seconds, its combined output)."""
    started = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            cwd=ROOT,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise MissingTool(f"{argv[0]} is not installed.") from exc
    seconds = time.monotonic() - started
    return done.returncode == 0, seconds, done.stdout or ""


def failure_report(name: str, output: str) -> list[str]:
    """The failed test names, the tail and where the full output was kept."""
    lines = output.strip().splitlines()
    named = [line for line in lines if FAILED_TEST.match(line)]
    report = [*named, *lines[-TAIL_LINES:]]
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix=f"check-changed-{name}-",
            suffix=".log",
            delete=False,
        ) as log:
            log.write(output)
    except OSError:
        # A full or unwritable temp directory must not stop the later steps.
        return report
    return [*report, f"full output: {log.name}"]


def run_steps(steps: list[tuple[str, list[str]]]) -> int:
    """Run all steps and print the report; 0 passed, 1 failed, 2 tool missing."""
    failed = missing = False
    for name, argv in steps:
        try:
            passed, seconds, output = run_step(argv)
        except MissingTool as exc:
            print(f"FAILED {name} (0.0s)\n  {exc}")
            missing = True
            continue
        print(f"{'ok' if passed else 'FAILED'} {name} ({seconds:.1f}s)")
        if not passed:
            failed = True
            for line in failure_report(name, output):
                print(f"  {line}")
    if missing:
        return 2
    return 1 if failed else 0


def touches_js(base: str) -> bool:
    """Whether committed, staged, unstaged or new files differ from the base."""
    fork = git("merge-base", base, "HEAD", cwd=ROOT).strip()
    changed = git("diff", "--name-only", fork, cwd=ROOT).splitlines()
    changed += git("ls-files", "--others", "--exclude-standard", cwd=ROOT).splitlines()
    return any(path.endswith(JS_SUFFIXES) for path in changed)


def build_steps(base: str, js: bool) -> list[tuple[str, list[str]]]:
    python = sys.executable
    steps = [
        ("tests", [python, "tests/run_tests.py", "--changed", "--base", base]),
        (
            "compile",
            [python, "-m", "compileall", "-q", "server.py", "backend", "tests"],
        ),
        ("quality", [python, "tools/quality_baseline.py"]),
    ]
    if js:
        files = sorted(
            path.relative_to(ROOT).as_posix() for path in ROOT.glob("tests/*.cjs")
        )
        steps.append(("node-tests", ["node", "--test", *files]))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument("--js", action="store_true", help="always run the Node tests")
    args = parser.parse_args(argv)
    try:
        js = args.js or touches_js(args.base)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_steps(build_steps(args.base, js))


if __name__ == "__main__":
    sys.exit(main())
