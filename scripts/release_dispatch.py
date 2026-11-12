"""Dispatch the daily release workflow and follow its release chain.

    python scripts/release_dispatch.py dispatch [--version 2.1.2]
    python scripts/release_dispatch.py follow [--version 2.1.2] [--since ISO]

`dispatch` starts `daily-release.yml` on develop and prints the run it started.
`follow` prints one line per link of the chain: the version PR, the promotion
PR to main, the GitHub Release, and the container publish run for that tag.
Exit 0 published, 1 a link failed or was closed unmerged, 2 bad input or a
failed gh call, 3 still in progress. It never merges, approves or reruns.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import UTC, datetime

from gh_cli import CliError, gh, gh_json

WORKFLOW = "daily-release.yml"
PUBLISH = "Test and publish container image"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_PR = re.compile(
    r"^chore\(release\): set application version to (\d+\.\d+\.\d+)$"
)
GREEN = {"success", "skipped", "neutral"}


def version_arg(text: str) -> str:
    if not VERSION.match(text):
        raise argparse.ArgumentTypeError("version must be MAJOR.MINOR.PATCH")
    return text


def dispatch(version: str | None) -> int:
    started = datetime.now(UTC).isoformat(timespec="seconds")
    extra = ["-f", f"release_version={version}"] if version else []
    gh("workflow", "run", WORKFLOW, "--ref", "develop", *extra)
    for _ in range(10):
        runs = gh_json(
            "run", "list", "--workflow", WORKFLOW, "--event", "workflow_dispatch",
            "--limit", "5", "--json", "databaseId,status,createdAt,url",
        )  # fmt: skip
        mine = [r for r in runs if r["createdAt"] >= started[:19]]
        if mine:
            run = mine[0]
            print(f"dispatched run {run['databaseId']} ({run['status']}): {run['url']}")
            print(f"next: python scripts/release_dispatch.py follow --since {started}")
            return 0
        time.sleep(3)
    print("dispatched, but the run is not listed yet; follow with --since " + started)
    return 3


def pull(title: str, base: str) -> dict | None:
    found = gh_json(
        "pr", "list", "--base", base, "--state", "all", "--search", f'"{title}" in:title',
        "--limit", "5", "--json", "number,title,state,mergedAt,createdAt,url",
    )  # fmt: skip
    exact = [p for p in found if p["title"] == title]
    return exact[0] if exact else None


def newest_version(since: str | None) -> str | None:
    found = gh_json(
        "pr", "list", "--base", "develop", "--state", "all", "--limit", "10",
        "--search", '"set application version to" in:title',
        "--json", "title,createdAt",
    )  # fmt: skip
    for pr in sorted(found, key=lambda p: p["createdAt"], reverse=True):
        match = VERSION_PR.match(pr["title"])
        if match and (not since or pr["createdAt"] >= since[:19]):
            return match[1]
    return None


def pr_state(pr: dict | None) -> str:
    if pr is None:
        return "pending"
    if pr["state"] == "MERGED":
        return "ok"
    return "failed" if pr["state"] == "CLOSED" else "pending"


def release_state(version: str) -> tuple[str, str]:
    try:
        data = gh_json(
            "release", "view", version, "--json", "tagName,isDraft,targetCommitish"
        )
    except CliError:
        return "pending", "not published yet"
    if data.get("isDraft"):
        return "pending", "draft"
    return "ok", f"published, target {str(data.get('targetCommitish'))[:12]}"


def publish_state(version: str) -> tuple[str, str]:
    runs = gh_json(
        "run", "list", "--workflow", PUBLISH, "--event", "release", "--limit", "10",
        "--json", "databaseId,status,conclusion,headBranch,url",
    )  # fmt: skip
    mine = [r for r in runs if r.get("headBranch") == version]
    if not mine:
        return "pending", "no publish run yet"
    run = mine[0]
    if run["status"] != "completed":
        return "pending", f"run {run['databaseId']} {run['status']}"
    state = "ok" if run["conclusion"] in GREEN else "failed"
    return state, f"run {run['databaseId']} {run['conclusion']}"


def follow(version: str | None, since: str | None) -> int:
    version = version or newest_version(since)
    if not version:
        print("pending version PR: none found yet")
        return 3
    links: list[tuple[str, str]] = []
    for name, title, base in (
        (
            "version PR",
            f"chore(release): set application version to {version}",
            "develop",
        ),
        ("promotion PR", f"chore(release): promote {version} to main", "main"),
    ):
        pr = pull(title, base)
        detail = f"#{pr['number']} {pr['state']}" if pr else "not created yet"
        links.append((pr_state(pr), f"{name} {detail}"))
    state, detail = release_state(version)
    links.append((state, f"release {version} {detail}"))
    state, detail = publish_state(version)
    links.append((state, f"publish {detail}"))
    for state, text in links:
        print(f"{state} {text}")
    states = {state for state, _ in links}
    if "failed" in states:
        return 1
    return 3 if "pending" in states else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("dispatch")
    start.add_argument("--version", type=version_arg)
    track = sub.add_parser("follow")
    track.add_argument("--version", type=version_arg)
    track.add_argument("--since")
    args = parser.parse_args(argv)
    try:
        if args.command == "dispatch":
            return dispatch(args.version)
        return follow(args.version, args.since)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
