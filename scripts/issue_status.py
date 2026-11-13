"""Print an issue's open checkboxes and the state of PRs that link it.

Run before reporting an issue as done: `python scripts/issue_status.py 1906`.
Exit code 1 means the issue is not done yet (open checkboxes or open PRs);
open boxes under an acceptance-criteria heading do not count.
"""

import json
import re
import subprocess
import sys

CHECKBOX = re.compile(r"^\s*[-*] \[ \] (.+)$", re.MULTILINE)

HEADING = re.compile(r"^(#{1,6}) +(.+)$")


def open_boxes(body):
    """Open box matches split into parts and acceptance criteria.

    A criterion sits under a heading starting with "Acceptance criteria", down to
    the next heading of the same or a higher level; headings inside code fences
    do not count. The closing summary covers criteria; parts keep an issue open.
    """
    body = body or ""
    parts, criteria, level, fenced, start = [], [], 0, False, 0
    for line in body.split("\n"):
        text, end = line.strip(), start + len(line)
        fenced ^= text.startswith(("```", "~~~"))
        if (heading := HEADING.match(text)) and not fenced:
            depth = len(heading[1])  # a deeper heading stays inside the section
            starts = heading[2].lower().startswith("acceptance criteria")
            level = depth if starts else level * (depth > level)
        if box := CHECKBOX.match(body, start, end):
            (criteria if level else parts).append(box)
        start = end + 1
    return parts, criteria


def open_checkboxes(body):
    return [m[1].strip() for m in open_boxes(body)[0]]


def gh_json(*args):
    output = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(output or "null")


def main(argv):
    try:
        (argument,) = argv[1:]
        issue = int(argument, 10)
        if issue <= 0:
            raise ValueError(argument)
        number = str(issue)
    except ValueError:
        print("usage: python scripts/issue_status.py <issue-number>", file=sys.stderr)
        return 2
    issue = gh_json("issue", "view", number, "--json", "state,body")
    pulls = gh_json(
        "pr",
        "list",
        "--state",
        "all",
        "--search",
        f"#{number} in:body",
        "--json",
        "number,state,title",
    )
    boxes = open_checkboxes(issue["body"])
    print(f"Issue #{number}: {issue['state']}")
    for item in boxes:
        print(f"  open checkbox: {item}")
    for item in open_boxes(issue["body"])[1]:
        print(f"  open criterion (issue_update close ticks it): {item[1].strip()}")
    for pull in pulls:
        print(f"  PR #{pull['number']} {pull['state']}: {pull['title']}")
    unfinished = boxes or any(pull["state"] == "OPEN" for pull in pulls)
    return 1 if unfinished else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
