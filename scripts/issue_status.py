"""Print an issue's open checkboxes and the state of PRs that link it.

Run before reporting an issue as done: `python scripts/issue_status.py 1906`.
Exit code 1 means the issue is not done yet (open checkboxes or open PRs).
"""

import json
import re
import subprocess
import sys

CHECKBOX = re.compile(r"^\s*[-*] \[ \] (.+)$", re.MULTILINE)


def open_checkboxes(body):
    return [item.strip() for item in CHECKBOX.findall(body or "")]


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
    for pull in pulls:
        print(f"  PR #{pull['number']} {pull['state']}: {pull['title']}")
    unfinished = boxes or any(pull["state"] == "OPEN" for pull in pulls)
    return 1 if unfinished else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
