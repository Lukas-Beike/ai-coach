"""Shared GitHub CLI and Git calls for the base-skill scripts.

The scripts pass every argument as a list (no shell), read text bodies from
files, and never print credentials: `gh` keeps its own authentication.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Token shapes that must never reach an issue, PR or comment body.
SECRET_SHAPES = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[A-Za-z0-9-]{10,}"
)
MAX_BODY = 60_000


class CliError(RuntimeError):
    """A failed command or a refused input; the message is safe to print."""


def run(
    program: str,
    *args: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        done = subprocess.run(
            [program, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        raise CliError(f"{program} is not installed.") from exc
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        # git prints progress ("To <remote>") before the line that says why.
        reason = next(
            (x for x in lines if x.startswith(("error", "fatal", " ! "))), None
        )
        raise CliError(
            f"{program} {' '.join(args[:2])} failed: "
            f"{reason or (lines[0] if lines else 'no output')}"
        )
    return done.stdout


def gh(*args: str) -> str:
    return run("gh", *args)


def gh_json(*args: str) -> Any:
    try:
        return json.loads(gh(*args) or "null")
    except json.JSONDecodeError as exc:
        raise CliError(f"gh {' '.join(args[:2])} returned invalid JSON.") from exc


def git(
    *args: str, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> str:
    return run("git", *args, cwd=cwd, env=env)


def read_body(path: str) -> str:
    """Read a Markdown body from a file and refuse empty, huge or secret-shaped text."""
    try:
        body = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot read body file {path}: {exc.strerror}") from exc
    if not body.strip():
        raise CliError(f"body file {path} is empty.")
    if len(body) > MAX_BODY:
        raise CliError(f"body file {path} exceeds {MAX_BODY} characters.")
    if SECRET_SHAPES.search(body):
        raise CliError(
            f"body file {path} contains a credential-shaped string; refused."
        )
    return body


def positive_int(text: str) -> int:
    value = int(text.lstrip("#"), 10)
    if value <= 0:
        raise ValueError(text)
    return value
