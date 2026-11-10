"""Remove merged, clean, idle Git worktrees (dry run unless --apply)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROTECTED_BRANCHES = {"develop", "main"}
DAY = 86400


def run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, check=False, capture_output=True, text=True, encoding="utf-8"
    )


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd)


def parse_worktrees(porcelain: str) -> list[dict]:
    entries = []
    for block in porcelain.strip().split("\n\n"):
        entry: dict = {"branch": None, "locked": False, "detached": False}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                entry["path"] = value
            elif key == "branch":
                entry["branch"] = value.removeprefix("refs/heads/")
            elif key == "detached":
                entry["detached"] = True
            elif key == "locked":
                entry["locked"] = True
        if "path" in entry:
            entries.append(entry)
    return entries


def same_path(left: str, right: str) -> bool:
    return Path(left).resolve() == Path(right).resolve()


def is_clean(path: str) -> bool:
    done = git("status", "--porcelain", "--untracked-files=all", cwd=path)
    return done.returncode == 0 and not done.stdout.strip()


def last_modified(path: str) -> float:
    """Newest of the worktree directory and its checkout/commit log."""
    done = git("rev-parse", "--absolute-git-dir", cwd=path)
    times = [Path(path).stat().st_mtime]
    if done.returncode == 0:
        gitdir = Path(done.stdout.strip())
        for name in ("logs/HEAD", "HEAD"):
            if (gitdir / name).exists():
                times.append((gitdir / name).stat().st_mtime)
    return max(times)


def merge_state(branch: str, base: str) -> str | None:
    """Return how the branch counts as merged, or None."""
    if git("merge-base", "--is-ancestor", branch, base).returncode == 0:
        return "ancestor"
    tip = git("rev-parse", branch).stdout.strip()
    done = run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "merged",
            "--json",
            "headRefOid",
            "--jq",
            ".[].headRefOid",
        ]
    )
    # A reused branch name must not match: the merged PR head has to be the local tip.
    if done.returncode == 0 and tip and tip in done.stdout.split():
        return "pr-merged"
    return None


def assess(entry, primary, current, base, idle_days, now) -> tuple[bool, str]:
    path = entry["path"]
    if same_path(path, primary):
        return False, "primary checkout"
    if same_path(path, current):
        return False, "current worktree"
    if entry["locked"]:
        return False, "locked"
    branch = entry["branch"]
    if not branch or branch in PROTECTED_BRANCHES:
        return False, "no feature branch"
    if not Path(path).is_dir():
        return False, "directory missing (use git worktree prune)"
    if not is_clean(path):
        return False, "uncommitted or untracked changes"
    merged = merge_state(branch, base)
    if not merged:
        return False, "branch not merged"
    idle = (now - last_modified(path)) / DAY
    if idle < idle_days:
        return False, f"modified {idle:.1f} days ago"
    return True, f"clean, {merged}, idle {idle:.1f} days"


def remove(entry: dict, merged_by_pr: bool) -> str | None:
    """Return an error message, or None on success."""
    done = git("worktree", "remove", entry["path"])
    if done.returncode != 0:
        return (done.stderr.strip().splitlines() or ["worktree remove failed"])[0]
    flag = "-D" if merged_by_pr else "-d"
    done = git("branch", flag, entry["branch"])
    if done.returncode != 0:
        return (done.stderr.strip().splitlines() or ["branch delete failed"])[0]
    return None


def main(argv: list[str] | None = None, now: float | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="remove (default: dry run)"
    )
    parser.add_argument("--idle-days", type=float, default=3.0)
    parser.add_argument("--min-free-gb", type=float, default=10.0)
    parser.add_argument("--base", default="origin/develop")
    args = parser.parse_args(argv)
    now = time.time() if now is None else now

    listing = git("worktree", "list", "--porcelain")
    top = git("rev-parse", "--show-toplevel")
    if listing.returncode != 0 or top.returncode != 0:
        print("prune_worktrees: not inside a Git repository.", file=sys.stderr)
        return 1
    entries = parse_worktrees(listing.stdout)
    primary, current = entries[0]["path"], top.stdout.strip()

    failed = False
    for entry in entries:
        ok, reason = assess(entry, primary, current, args.base, args.idle_days, now)
        label = entry["branch"] or "(detached)"
        if not ok:
            print(f"keep   {entry['path']} [{label}]: {reason}")
        elif not args.apply:
            print(f"prune  {entry['path']} [{label}]: {reason} (dry run)")
        else:
            error = remove(
                entry, merge_state(entry["branch"], args.base) == "pr-merged"
            )
            failed |= error is not None
            print(
                f"failed {entry['path']} [{label}]: {error}"
                if error
                else f"removed {entry['path']} [{label}]"
            )

    free_gb = shutil.disk_usage(primary).free / 1024**3
    print(f"Free disk space: {free_gb:.1f} GB")
    if free_gb < args.min_free_gb:
        print(f"WARNING: below {args.min_free_gb:g} GB free.", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
