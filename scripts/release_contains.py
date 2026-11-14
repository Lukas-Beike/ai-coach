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


def resolve(name: str) -> str:
    return git(
        "rev-parse", "--verify", "--end-of-options", f"{name}^{{commit}}"
    ).strip()


def is_ancestor(commit: str, of: str) -> bool:
    done = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, of],
        capture_output=True,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise CliError("git merge-base failed")
    return done.returncode == 0


def release_base(tag: str, branch: str) -> str | None:
    """The newest branch commit with the tag's tree, not newer than the tag.

    A later revert can bring the same tree back; it came after the promotion.
    """
    tree, when = git("log", "-1", "--format=%T %ct", tag).split()
    for line in git("log", branch, "--format=%H %T %ct").splitlines():
        commit, candidate, stamp = line.split()
        if candidate == tree and int(stamp) <= int(when):
            return commit
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("commit")
    parser.add_argument("tag")
    parser.add_argument("--branch", default="origin/develop")
    args = parser.parse_args(argv)
    try:
        commit, tag = resolve(args.commit), resolve(args.tag)
        # A tag on the branch history needs no tree match.
        base = (
            tag if is_ancestor(commit, tag) else release_base(tag, resolve(args.branch))
        )
        contained = base is not None and is_ancestor(commit, base)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if base is None:
        print(
            f"error: no {args.branch} commit has the tree of {args.tag}",
            file=sys.stderr,
        )
        return 2
    verdict = "contained in" if contained else "not contained in"
    print(f"{commit[:10]} {verdict} {args.tag} (promoted from {base[:10]})")
    return 0 if contained else 1


if __name__ == "__main__":
    sys.exit(main())
