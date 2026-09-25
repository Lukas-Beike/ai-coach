"""Resolve and verify the immutable source used by every release check and build."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess

SAFE_SOURCE_PATTERN = re.compile(r"^[\da-zA-Z][\da-zA-Z._/-]*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
COMMIT_SHA_PATTERN = re.compile(r"^[\da-f]{40}$")
APP_VERSION_PATTERN = re.compile(r'^APP_VERSION = "(\d+\.\d+\.\d+)"$', re.M)
SAFE_ARG_PATTERN = re.compile(r"^[\da-zA-Z._/:@=^{}-]+$")


def git(repository: Path, *arguments: str) -> str:
    for argument in arguments:
        if not SAFE_ARG_PATTERN.fullmatch(argument):
            raise ValueError(f"Unsafe git command argument: {argument!r}")
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _validate_source_ref(source_ref: str, release_tag: str) -> None:
    if (
        not source_ref
        or not SAFE_SOURCE_PATTERN.fullmatch(source_ref)
        or ".." in source_ref
        or release_tag.startswith("-")
    ):
        raise ValueError("A valid source reference is required")
    if not release_tag:
        return
    if not VERSION_PATTERN.fullmatch(release_tag):
        raise ValueError("Release tag must be an application version")
    if source_ref != release_tag and not COMMIT_SHA_PATTERN.fullmatch(source_ref):
        raise ValueError("Release source must be its tag or an immutable commit SHA")


def _resolve_commit(repository: Path, source_ref: str) -> str:
    if not SAFE_SOURCE_PATTERN.fullmatch(source_ref) or ".." in source_ref:
        raise ValueError("A valid source reference is required")
    try:
        return git(repository, "rev-parse", "--verify", f"{source_ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return git(repository, "rev-parse", "--verify", f"refs/remotes/origin/{source_ref}^{{commit}}")


def _verify_release_integrity(repository: Path, source: str, release_tag: str) -> None:
    if not VERSION_PATTERN.fullmatch(release_tag):
        raise ValueError("Release tag must be an application version")
    if not COMMIT_SHA_PATTERN.fullmatch(source):
        raise ValueError("Release source must be its tag or an immutable commit SHA")
    tagged = git(repository, "rev-parse", "--verify", f"refs/tags/{release_tag}^{{commit}}")
    if source != tagged:
        raise ValueError("source_ref and release_tag identify different commits")
    try:
        git(repository, "merge-base", "--is-ancestor", source, "refs/remotes/origin/main")
    except subprocess.CalledProcessError as error:
        raise ValueError("Release source must belong to protected main history") from error
    content = git(repository, "show", f"{source}:server.py")
    version = APP_VERSION_PATTERN.search(content)
    if not version or version.group(1) != release_tag:
        raise ValueError("Release tag does not match APP_VERSION at the resolved source")


def resolve(repository: Path, source_ref: str, release_tag: str = "") -> str:
    _validate_source_ref(source_ref, release_tag)
    source = _resolve_commit(repository, source_ref)
    if release_tag:
        _verify_release_integrity(repository, source, release_tag)
    return source


def verify(repository: Path, expected_sha: str, release_tag: str) -> None:
    if not COMMIT_SHA_PATTERN.fullmatch(expected_sha):
        raise ValueError("Build checkout differs from the tested source SHA")
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
