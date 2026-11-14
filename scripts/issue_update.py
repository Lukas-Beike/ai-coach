"""Update one GitHub issue: start, comment, tick, label, assign, finish, close.

    python scripts/issue_update.py start <n>
    python scripts/issue_update.py comment <n> --body-file F
    python scripts/issue_update.py tick <n> --part "<start of the checkbox text>"
    python scripts/issue_update.py label <n> [--add X] [--remove Y]
    python scripts/issue_update.py assign <n> [--add X] [--remove Y]
    python scripts/issue_update.py finish <n>
    python scripts/issue_update.py close <n> --body-file F

Exit 0: done; 1: refused (ambiguous or missing checkbox, open checkboxes or an
open PR on close); 2: bad input or a failed gh call. Close ticks the open boxes
under an `Acceptance criteria` or `Acceptance` heading and accepts an issue a merge already closed.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from gh_cli import CliError, gh, gh_json, positive_int, read_body
from issue_status import CHECKBOX, linked_pulls, open_boxes, open_checkboxes

IN_PROGRESS = "in progress"


def edit(number: int, *args: str) -> str:
    return gh("issue", "edit", str(number), *args)


def tick(number: int, part: str) -> int:
    wanted = part.strip().lower()
    if not wanted:
        raise CliError("--part must not be empty.")
    body = gh_json("issue", "view", str(number), "--json", "body")["body"] or ""
    hits = [
        m for m in CHECKBOX.finditer(body) if m[1].strip().lower().startswith(wanted)
    ]
    if len(hits) != 1:
        found = "no open checkbox" if not hits else f"{len(hits)} open checkboxes"
        print(f"refused: {found} starts with {part!r}; give a longer, unique start")
        for hit in hits:
            print(f"  open checkbox: {hit[1].strip()}")
        return 1
    write_ticked(number, body, hits)
    print(f"ticked #{number}: {hits[0][1].strip()}")
    return 0


def write_ticked(number: int, body: str, boxes: list[re.Match[str]]) -> None:
    for match in boxes:  # "[x] " replaces the same-length "[ ] " before the text
        box = match.start(1) - 4
        body = body[:box] + "[x] " + body[box + 4 :]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "body.md"
        path.write_text(body, encoding="utf-8", newline="")
        edit(number, "--body-file", str(path))


def blockers(number: int) -> tuple[dict[str, Any], list[str]]:
    """The issue's state and body, and what keeps it from being done."""
    issue = gh_json("issue", "view", str(number), "--json", "state,body")
    found = [f"open checkbox: {item}" for item in open_checkboxes(issue["body"])]
    for pull in linked_pulls(number, gh_json):
        if pull["state"] == "OPEN":
            found.append(f"open PR #{pull['number']}: {pull['title']}")
    return issue, found


def close(number: int, body_file: str) -> int:
    read_body(body_file)
    issue, found = blockers(number)
    if found:
        print(f"refused: #{number} is not done")
        for item in found:
            print(f"  {item}")
        return 1
    # The summary carries the evidence for the acceptance criteria still unticked;
    # ticking first keeps a rerun after a failed edit from posting it twice.
    body = issue["body"] or ""
    if criteria := open_boxes(body)[1]:
        write_ticked(number, body, criteria)
    gh("issue", "comment", str(number), "--body-file", body_file)
    edit(number, "--remove-label", IN_PROGRESS)
    is_open = issue["state"] == "OPEN"
    # A merged "Closes #N" PR has usually closed the issue already.
    if is_open:
        gh("issue", "close", str(number))
    print(f"closed #{number}" if is_open else f"#{number} was already closed")
    return 0


def changes(args: argparse.Namespace, flag: str) -> list[str]:
    if not (args.add or args.remove):
        raise CliError("give at least one --add or --remove.")
    out: list[str] = []
    for value in args.add:
        out += [f"--add-{flag}", value]
    for value in args.remove:
        out += [f"--remove-{flag}", value]
    return out


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True)
    for name in ("start", "comment", "tick", "label", "assign", "finish", "close"):
        item = sub.add_parser(name)
        item.add_argument("number", type=positive_int)
        if name in ("comment", "close"):
            item.add_argument("--body-file", required=True)
        if name == "tick":
            item.add_argument("--part", required=True)
        if name in ("label", "assign"):
            item.add_argument("--add", action="append", default=[])
            item.add_argument("--remove", action="append", default=[])
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    n = args.number
    try:
        match args.command:
            case "start":
                edit(n, "--add-assignee", "@me", "--add-label", IN_PROGRESS)
            case "comment":
                read_body(args.body_file)
                gh("issue", "comment", str(n), "--body-file", args.body_file)
            case "tick":
                return tick(n, args.part)
            case "label":
                edit(n, *changes(args, "label"))
            case "assign":
                edit(n, *changes(args, "assignee"))
            case "finish":
                edit(n, "--remove-label", IN_PROGRESS)
            case "close":
                return close(n, args.body_file)
    except (CliError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{args.command} #{n}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
