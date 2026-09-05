"""Resolve and verify the immutable source used by every release check and build."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess


def git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(repository), *arguments], text=True, stderr=subprocess.PIPE).strip()


def resolve(repository: Path, source_ref: str, release_tag: str = "") -> str:
    if not source_ref or source_ref.startswith("-") or release_tag.startswith("-"):
        raise ValueError("A valid source reference is required")
    if release_tag:
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_tag):
            raise ValueError("Release tag must be an application version")
        if source_ref != release_tag and not re.fullmatch(r"[0-9a-f]{40}", source_ref):
            raise ValueError("Release source must be its tag or an immutable commit SHA")
    try:
        source = git(repository, "rev-parse", "--verify", f"{source_ref}^{{commit}}")
    except subprocess.CalledProcessError:
        source = git(repository, "rev-parse", "--verify", f"refs/remotes/origin/{source_ref}^{{commit}}")
    if release_tag:
        tagged = git(repository, "rev-parse", "--verify", f"refs/tags/{release_tag}^{{commit}}")
        if source != tagged:
            raise ValueError("source_ref and release_tag identify different commits")
        try:
            git(repository, "merge-base", "--is-ancestor", source, "refs/remotes/origin/main")
        except subprocess.CalledProcessError as error:
            raise ValueError("Release source must belong to protected main history") from error
        content = git(repository, "show", f"{source}:server.py")
        version = re.search(r'^APP_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', content, re.M)
        if not version or version.group(1) != release_tag:
            raise ValueError("Release tag does not match APP_VERSION at the resolved source")
    return source


def verify(repository: Path, expected_sha: str, release_tag: str) -> None:
    if git(repository, "rev-parse", "HEAD") != expected_sha:
        raise ValueError("Build checkout differs from the tested source SHA")
    if resolve(repository, expected_sha, release_tag) != expected_sha:
        raise ValueError("Source verification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=os.environ.get("SOURCE_REF", ""))
    parser.add_argument("--release-tag", default=os.environ.get("RELEASE_TAG", ""))
    parser.add_argument("--verify", default="")
    args = parser.parse_args()
    repository = Path.cwd()
    if args.verify:
        verify(repository, args.verify, args.release_tag)
        return
    source = resolve(repository, args.source, args.release_tag)
    print(f"Resolved source: {source}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"source_sha={source}\n")


if __name__ == "__main__":
    main()
