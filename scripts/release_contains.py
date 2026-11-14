"""Tell whether a release tag contains a develop commit; read-only.

    python scripts/release_contains.py <commit> <tag> [--branch origin/develop]

A release reaches `main` by a squash promote commit, so develop commits are
never ancestors of a tag and `git merge-base --is-ancestor` always says no
(#2800). The promotion keeps develop's tree (`merge -s ours`), so the tag's
tree equals the tree of the develop commit it was promoted from. The script
finds that commit on the branch and answers by ancestry against it.
Fetch the branch and tags first. Exit 0: contained; 1: not contained;
2: bad input, a failed git call, or no branch commit with the tag's tree.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from gh_cli import CliError, git


def release_base(tag: str, branch: str) -> str | None:
    """The newest branch commit whose tree is the tag's tree."""
    tree = git("rev-parse", f"{tag}^{{tree}}").strip()
    for line in git("log", branch, "--format=%H %T").splitlines():
        commit, _, candidate = line.partition(" ")
        if candidate == tree:
            return commit
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("commit")
    parser.add_argument("tag")
    parser.add_argument("--branch", default="origin/develop")
    args = parser.parse_args(argv)
    try:
        commit = git("rev-parse", "--verify", f"{args.commit}^{{commit}}").strip()
        base = release_base(args.tag, args.branch)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if base is None:
        print(
            f"error: no {args.branch} commit has the tree of {args.tag}",
            file=sys.stderr,
        )
        return 2
    code = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, base], check=False
    ).returncode
    if code not in (0, 1):
        print("error: git merge-base failed", file=sys.stderr)
        return 2
    verdict = "not contained in" if code else "contained in"
    print(f"{commit[:10]} {verdict} {args.tag} (promoted from {base[:10]})")
    return code


if __name__ == "__main__":
    sys.exit(main())
