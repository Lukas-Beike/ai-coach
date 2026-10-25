"""Scan outgoing Git contents, never incoming prompts or the live worktree."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def git(*args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], input=input, capture_output=True, check=True
    ).stdout


def outgoing_objects(updates: str) -> set[str]:
    objects = set()
    for line in updates.splitlines():
        _, local, _, remote = line.split()
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
        objects.update(
            git("rev-list", "--objects", "--no-object-names", local, *exclusions)
            .decode("ascii")
            .splitlines()
        )
    return objects


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
    contents = [
        tuple(row.split())
        for row in metadata.decode("ascii").splitlines()
        if row.split()[1] in {"blob", "commit", "tag"}
    ]
    with tempfile.TemporaryDirectory(prefix="ai-coach-push-scan-") as temp:
        # Scan batches to bound disk use and Windows command-line length.
        for start in range(0, len(contents), 35):
            paths = []
            for oid, kind in contents[start : start + 35]:
                path = Path(temp) / (oid + ".txt")
                path.write_bytes(git("cat-file", kind, oid))
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
