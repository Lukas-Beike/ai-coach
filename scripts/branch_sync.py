"""Rebase the current feature branch onto the target and optionally push it.

    python scripts/branch_sync.py [--onto origin/develop] [--push]

Refuses on develop, main, a detached HEAD and a dirty working tree. Fetches
origin, rebases, checks every commit subject against the Conventional Commit
types, and with --push pushes with --force-with-lease through the repository
hooks (never --no-verify). The hooks need the SonarQube CLI on PATH.

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


def invalid_subjects(onto: str) -> list[str]:
    subjects = git("log", "--format=%s", f"{onto}..HEAD").splitlines()
    return [s for s in subjects if not SUBJECT.match(s)]


def sync(onto: str, push: bool) -> int:
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
    git("fetch", "origin")
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
        return 1
    bad = invalid_subjects(onto)
    if bad:
        print("invalid commit subjects (need <type>(<scope>): <description>):")
        for subject in bad:
            print(f"  {subject}")
        return 1
    if push:
        git(
            "-c", "core.hooksPath=.githooks", "push", "--force-with-lease", "-u",
            "origin", branch, env=env,
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
    args = parser.parse_args(argv)
    try:
        return sync(args.onto, args.push)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
