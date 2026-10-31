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


def added_content(updates: str) -> tuple[set[str], set[tuple[str, bytes]]]:
    """Split outgoing blob content into whole blobs and per-file added-line runs.

    New and binary files are scanned whole. For an edited text file only the
    added lines are scanned, in order, so findings already on the base cannot
    block an unrelated change and multi-line secrets stay intact.
    """
    whole: set[str] = set()
    runs: set[tuple[str, bytes]] = set()
    for local, exclusions in outgoing_revisions(updates):
        diff = git(
            *("log", "--format=", "-p", "-m", "-U0", "--full-index", "--no-renames"),
            *("--no-color", "--no-ext-diff", "--no-textconv", local, *exclusions),
        )
        suffix, new_blob, in_hunk = "", "", False
        rows: list[bytes] = []
        # A final sentinel row flushes the last file.
        for row in [*diff.split(b"\n"), b"diff --git a/ b/"]:
            if row.startswith(b"diff --git "):
                if rows:
                    runs.add((suffix, b"\n".join(rows)))
                rows, in_hunk, new_blob = [], False, ""
                suffix = Path(
                    row.rsplit(b" b/", 1)[-1].decode("utf-8", "replace")
                ).suffix
                if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
                    suffix = ""
            elif in_hunk:
                if row.startswith(b"+"):
                    rows.append(row[1:])
            elif row.startswith(b"@@"):
                in_hunk = True
            elif row.startswith(b"index "):
                old, new_blob = row.split()[1].decode("ascii").split("..")
                if set(old) == {"0"} and set(new_blob) != {"0"}:
                    whole.add(new_blob)
            elif row.startswith(b"Binary files") and new_blob:
                whole.add(new_blob)
    whole = {oid for oid in whole if set(oid) != {"0"}}
    return whole, runs


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
    whole, runs = added_content(updates)
    sources = [(oid + ".txt", git("cat-file", kind, oid)) for oid, kind in messages]
    sources += [(oid + ".txt", git("cat-file", "blob", oid)) for oid in sorted(whole)]
    sources += [
        (f"added-{index}{suffix or '.txt'}", data)
        for index, (suffix, data) in enumerate(sorted(runs))
    ]
    with tempfile.TemporaryDirectory(prefix="ai-coach-push-scan-") as temp:
        # Scan batches to bound disk use and Windows command-line length.
        for start in range(0, len(sources), 35):
            paths = []
            for name, data in sources[start : start + 35]:
                path = Path(temp) / name
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
