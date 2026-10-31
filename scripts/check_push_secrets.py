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


def file_content(section: bytes) -> tuple[str, str, bytes]:
    """Return suffix, whole-blob id to scan (or empty) and added lines of one file diff."""
    head, _, body = section.partition(b"\n@@")
    suffix = Path(
        head.split(b"\n", 1)[0].rsplit(b" b/", 1)[-1].decode("utf-8", "replace")
    ).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        suffix = ""
    whole = ""
    index = re.search(rb"^index ([0-9a-f,]+)\.\.([0-9a-f]+)", head, re.MULTILINE)
    if index and index[2].strip(b"0"):
        new_file = not index[1].strip(b"0,")
        if new_file or b"\nBinary files" in head:
            whole = index[2].decode("ascii")
    if not body:
        return suffix, whole, b""
    # Combined diffs prefix one column per parent; keep lines new to all.
    rows = []
    for hunk in re.split(rb"(?m)^(?=@@)", b"@@" + body)[1:]:
        header, _, lines = hunk.partition(b"\n")
        columns = header.split()[0].count(b"@") - 1
        rows += [
            row[columns:]
            for row in lines.split(b"\n")
            if row[:columns] == b"+" * columns
        ]
    return suffix, whole, b"\n".join(rows)


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
            *("log", "--format=", "-p", "--cc", "--root", "-U0", "--full-index"),
            *("--no-renames", "--no-color", "--no-ext-diff", "--no-textconv"),
            local,
            *exclusions,
        )
        for section in re.split(rb"(?m)^diff --(?:git|cc) ", diff)[1:]:
            suffix, blob, added = file_content(section)
            if blob:
                whole.add(blob)
            if added:
                runs.add((suffix, added))
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
