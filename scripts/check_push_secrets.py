"""Scan outgoing Git contents, never incoming prompts or the live worktree."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def git(*args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], input=input, capture_output=True, check=True
    ).stdout


def outgoing_revisions(updates: str) -> list[tuple[str, list[str]]]:
    revisions = []
    for line in updates.splitlines():
        _, local, _, remote = line.split()
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", local):
            raise ValueError("Invalid Git object ID; push refused")
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", remote):
            raise ValueError("Invalid Git object ID; push refused")
        if set(local) == {"0"}:
            continue
        # A remote ref can have advanced without its new tip being fetched.
        known_remote = (
            set(remote) != {"0"}
            and subprocess.run(
                ["git", "cat-file", "-e", remote], capture_output=True, check=False
            ).returncode
            == 0
        )
        exclusions = ["^" + remote] if known_remote else ["--not", "--remotes"]
        revisions.append((local, exclusions))
    return revisions


def outgoing_objects(updates: str) -> set[str]:
    objects = set()
    for local, exclusions in outgoing_revisions(updates):
        objects.update(
            git("rev-list", "--objects", "--no-object-names", local, *exclusions)
            .decode("ascii")
            .splitlines()
        )
    return objects


def added_lines(updates: str) -> set[bytes]:
    """Lines the outgoing commits add; pre-existing lines of touched files stay unscanned."""
    lines = set()
    for local, exclusions in outgoing_revisions(updates):
        diff = git(
            *("log", "--format=", "-p", "-c", "-U0", "--no-color", "--no-ext-diff"),
            "--no-textconv",
            local,
            *exclusions,
        )
        lines.update(
            row[1:]
            for row in diff.split(b"\n")
            if row.startswith(b"+") and not row.startswith(b"+++")
        )
    return lines


def check(updates: str) -> int:
    objects = outgoing_objects(updates)
    if not objects:
        return 0
    scanner = shutil.which("sonar")
    if not scanner:
        raise RuntimeError("Sonar CLI unavailable; push refused")
    metadata = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        input="".join(oid + "\n" for oid in sorted(objects)).encode("ascii"),
    )
    messages = [
        tuple(row.split())
        for row in metadata.decode("ascii").splitlines()
        if row.split()[1] in {"commit", "tag"}
    ]
    sources = [(oid, git("cat-file", kind, oid)) for oid, kind in messages]
    ordered = sorted(added_lines(updates))
    sources += [
        (f"added-{start}", b"\n".join(ordered[start : start + 2000]))
        for start in range(0, len(ordered), 2000)
    ]
    with tempfile.TemporaryDirectory(prefix="ai-coach-push-scan-") as temp:
        # Scan batches to bound disk use and Windows command-line length.
        for start in range(0, len(sources), 35):
            paths = []
            for name, data in sources[start : start + 35]:
                path = Path(temp) / (name + ".txt")
                path.write_bytes(data)
                paths.append(str(path))
            result = subprocess.run(
                [scanner, "analyze", "secrets", *paths],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            if result.returncode:
                raise RuntimeError(
                    "Secret scan failed or reported a finding; push refused"
                )
            for filename in paths:
                Path(filename).unlink()
    print("Outgoing Git secret scan passed")
    return 0


def main() -> int:
    try:
        return check(sys.stdin.read())
    except ValueError, OSError, subprocess.SubprocessError, RuntimeError:
        # Git/scanner errors can contain file contents or remote credentials.
        print(
            "Outgoing Git secret check failed; push refused. Check Sonar availability and outgoing commits locally.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
