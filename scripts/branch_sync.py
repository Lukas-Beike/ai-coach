"""Rebase the current feature branch onto the target and optionally push it.

    python scripts/branch_sync.py [--onto origin/develop] [--push] [--allow-root <file>]

Refuses on develop, main, a detached HEAD and a dirty working tree. Fetches
origin (retrying a ref lock held by a parallel worktree), rebases, checks every commit subject against the Conventional Commit
types, and with --push pushes with --force-with-lease through the repository
hooks (never --no-verify). The hooks need the SonarQube CLI on PATH. A push
that adds a file at the repository root is refused unless --allow-root names it.

Exit 0: in sync (and pushed); 1: refused, rebase conflict (left in progress:
resolve it or run `git rebase --abort`) or invalid subjects; 2: bad input,
missing SonarQube CLI or a failed git call.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from gh_cli import CliError, git

PROTECTED = {"develop", "main"}
TYPES = "build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test"
SUBJECT = re.compile(rf"^(?:{TYPES})(?:\([a-z0-9][a-z0-9-]*\))?!?: \S")


def sonar_dirs(env: Mapping[str, str], home: Path) -> list[Path]:
    local = env.get("LOCALAPPDATA")
    found = [Path(local) / "sonarqube-cli" / "bin"] if local else []
    return [*found, home / ".sonar" / "sonarqube-cli" / "bin", home / ".local" / "bin"]


def push_env(env: Mapping[str, str], home: Path) -> dict[str, str]:
    """A copy of env whose PATH finds the SonarQube CLI, or a CliError."""
    result = dict(env)
    if shutil.which("sonar", path=env.get("PATH")):
        return result
    for directory in sonar_dirs(env, home):
        if shutil.which("sonar", path=str(directory)):
            result["PATH"] = f"{directory}{os.pathsep}{env.get('PATH', '')}"
            return result
    raise CliError(
        "the pre-push hook needs the SonarQube CLI (sonar); install it first "
        "(setup prerequisite) so it is on PATH."
    )


FETCH_ATTEMPTS = 3


def fetch() -> None:
    """Fetch origin; retry while a parallel worktree holds a ref lock (#2828).

    A persistent failure raises, so the rebase never runs on a stale target.
    """
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            git("fetch", "origin")
            return
        except CliError as exc:
            if "cannot lock ref" not in str(exc) or attempt == FETCH_ATTEMPTS:
                raise
            print(
                f"fetch hit a ref lock (attempt {attempt}); retrying", file=sys.stderr
            )
            time.sleep(attempt)


def invalid_subjects(onto: str) -> list[str]:
    subjects = git("log", "--format=%s", f"{onto}..HEAD").splitlines()
    return [s for s in subjects if not SUBJECT.match(s)]


def rebased(onto: str) -> bool:
    """Rebase onto the target; on a conflict, leave it in progress and list it."""
    try:
        git("rebase", onto)
    except CliError as exc:
        conflicts = git("diff", "--name-only", "--diff-filter=U").split()
        if not conflicts:
            raise
        print(f"conflict: rebase onto {onto} stopped in {len(conflicts)} file(s)")
        for name in conflicts:
            print(f"  {name}")
        print("hint: resolve and `git rebase --continue`, or `git rebase --abort`")
        print(f"detail: {exc}", file=sys.stderr)
        return False
    return True


def outgoing_problems(onto: str, push: bool, allowed: frozenset[str]) -> bool:
    """Print invalid subjects and, for a push, new root files; True if any."""
    problems = [
        ("invalid commit subjects (need <type>(<scope>): <description>):", s)
        for s in invalid_subjects(onto)
    ]
    if push:
        added = git(
            *("-c", "core.quotePath=false", "diff", "--name-only", "--no-renames"),
            *("--diff-filter=A", f"{onto}...HEAD"),
        )
        # A stray root file is usually a session artefact (a mistyped redirect).
        problems += [
            ("refused: new root files; remove them or pass --allow-root <file>:", n)
            for n in added.splitlines()
            if n and "/" not in n and n not in allowed
        ]
    heading = None
    for title, item in problems:
        if title != heading:
            print(title)
            heading = title
        print(f"  {item}")
    return bool(problems)


def sync(onto: str, push: bool, allowed: frozenset[str] = frozenset()) -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD" or branch in PROTECTED:
        print(
            f"refused: on {branch if branch != 'HEAD' else 'a detached HEAD'}; use a feature branch"
        )
        return 1
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("refused: uncommitted changes; commit or stash them first")
        return 1
    env = push_env(os.environ, Path.home()) if push else None
    # The lease must name the remote tip seen before this run's fetch, or the
    # fetch moves origin/<branch> and the lease can no longer protect remote work.
    try:
        leased = git("rev-parse", "--verify", "--quiet", f"origin/{branch}").strip()
    except CliError:
        leased = ""  # never pushed: the push only succeeds while it stays absent
    fetch()
    if not rebased(onto):
        return 1
    if outgoing_problems(onto, push, allowed):
        return 1
    if push:
        git(
            "-c", "core.hooksPath=.githooks", "push",
            f"--force-with-lease={branch}:{leased}", "-u", "origin", branch, env=env,
        )  # fmt: skip
        print(f"pushed: {branch}")
    behind, ahead = git("rev-list", "--left-right", "--count", f"{onto}...HEAD").split()
    print(
        f"head {git('rev-parse', '--short', 'HEAD').strip()} on {branch}: ahead {ahead}, behind {behind}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--onto", default="origin/develop")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--allow-root", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        return sync(args.onto, args.push, frozenset(args.allow_root))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
