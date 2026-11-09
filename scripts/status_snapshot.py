"""Print a compact, read-only repository status from the GitHub CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

PASSING = {"SUCCESS", "SKIPPED", "NEUTRAL"}
NONE = "  none"
SUBJECT_PR = re.compile(r"\(#(\d+)\)\s*$")


class SnapshotError(RuntimeError):
    pass


def gh(*args: str) -> str:
    try:
        done = subprocess.run(
            ["gh", *args], check=False, capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise SnapshotError("The GitHub CLI (gh) is not installed.") from exc
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise SnapshotError(
            f"gh {' '.join(args[:2])} failed: {detail[0] if detail else 'no output'}"
        )
    return done.stdout


def gh_json(*args: str):
    try:
        return json.loads(gh(*args) or "null")
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"gh {' '.join(args[:2])} returned invalid JSON.") from exc


def latest_release(repo: str) -> dict:
    data = gh_json("release", "view", "--repo", repo, "--json", "tagName,publishedAt")
    return {"tag": data["tagName"], "published_at": data["publishedAt"]}


def release_promotion(repo: str, tag: str) -> dict | None:
    """Main is squash-promoted, so locate the promotion PR instead of comparing tags."""
    prs = gh_json(
        "pr", "list", "--repo", repo, "--base", "main", "--state", "merged",
        "--limit", "20", "--json", "number,title,mergedAt,headRefOid",
    )  # fmt: skip
    for pr in prs:
        if re.search(rf"\b{re.escape(tag)}\b", pr["title"]):
            return pr
    return prs[0] if prs else None


def merged_since(repo: str, promotion: dict | None) -> list[dict]:
    if not promotion:
        return []
    data = gh_json(
        "api", f"repos/{repo}/compare/{promotion['headRefOid']}...develop",
        "--jq", "[.commits[] | {sha: .sha, message: .commit.message, "
        "date: .commit.committer.date}]",
    )  # fmt: skip
    merged = []
    for commit in data:
        subject = commit["message"].splitlines()[0]
        match = SUBJECT_PR.search(subject)
        merged.append(
            {
                "number": int(match.group(1)) if match else None,
                "title": SUBJECT_PR.sub("", subject).rstrip(),
                "merged_at": commit["date"],
            }
        )
    return merged


def open_pull_requests(repo: str) -> list[dict]:
    data = gh_json(
        "pr", "list", "--repo", repo, "--state", "open", "--limit", "50", "--json",
        "number,title,baseRefName,mergeStateStatus,autoMergeRequest,statusCheckRollup",
    )  # fmt: skip
    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "base": pr["baseRefName"],
            "merge_state": pr["mergeStateStatus"],
            "auto_merge": bool(pr.get("autoMergeRequest")),
            "open_checks": open_checks(pr.get("statusCheckRollup") or []),
        }
        for pr in data
    ]


def open_checks(rollup: list[dict]) -> list[str]:
    names = []
    for item in rollup:
        if "context" in item:
            state, name = item.get("state"), item["context"]
        else:
            name = item.get("name", "?")
            state = (
                item.get("conclusion")
                if item.get("status") == "COMPLETED"
                else "PENDING"
            )
        if state not in PASSING:
            names.append(f"{name} ({str(state or 'PENDING').lower()})")
    return names


def release_runs(repo: str) -> list[dict]:
    data = gh_json(
        "run", "list", "--repo", repo, "--workflow", "daily-release.yml",
        "--limit", "5", "--json", "event,status,conclusion,createdAt",
    )  # fmt: skip
    return [
        {
            "event": run["event"],
            "status": run["status"],
            "conclusion": run["conclusion"] or None,
            "created_at": run["createdAt"],
        }
        for run in data
    ]


def labelled_issues(repo: str, label: str) -> list[dict]:
    data = gh_json(
        "issue", "list", "--repo", repo, "--state", "open", "--label", label,
        "--limit", "50", "--json", "number,title",
    )  # fmt: skip
    return [{"number": issue["number"], "title": issue["title"]} for issue in data]


def collect(repo: str) -> dict:
    release = latest_release(repo)
    promotion = release_promotion(repo, release["tag"])
    return {
        "repo": repo,
        "release": release,
        "promotion_pr": promotion["number"] if promotion else None,
        "merged_since_release": merged_since(repo, promotion),
        "open_prs": open_pull_requests(repo),
        "release_runs": release_runs(repo),
        "release_blockers": labelled_issues(repo, "release-blocker"),
        "in_progress": labelled_issues(repo, "in progress"),
    }


def render(snapshot: dict) -> str:
    release = snapshot["release"]
    lines = [
        f"{snapshot['repo']}: release {release['tag']} ({release['published_at']})",
        f"Merged on develop since release ({len(snapshot['merged_since_release'])}):",
    ]
    lines += [
        f"  #{pr['number']} {pr['title']} ({pr['merged_at']})"
        for pr in snapshot["merged_since_release"]
    ] or [NONE]
    lines.append(f"Open PRs ({len(snapshot['open_prs'])}):")
    for pr in snapshot["open_prs"]:
        auto = "auto-merge" if pr["auto_merge"] else "no auto-merge"
        checks = ", ".join(pr["open_checks"]) or "all checks passing"
        lines.append(f"  #{pr['number']} {pr['merge_state']}, {auto}: {checks}")
    if not snapshot["open_prs"]:
        lines.append(NONE)
    lines.append("Daily release runs:")
    lines += [
        f"  {run['created_at']} {run['event']} {run['status']}"
        f" {run['conclusion'] or '-'}"
        for run in snapshot["release_runs"]
    ] or [NONE]
    for key, title in (
        ("release_blockers", "Release blockers"),
        ("in_progress", "In progress"),
    ):
        lines.append(f"{title}:")
        lines += [f"  #{i['number']} {i['title']}" for i in snapshot[key]] or [NONE]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--repo", help="OWNER/NAME (default: current repository)")
    args = parser.parse_args(argv)
    try:
        repo = (
            args.repo
            or gh(
                "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"
            ).strip()
        )
        snapshot = collect(repo)
    except SnapshotError as exc:
        print(f"status_snapshot: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(snapshot, indent=2) if args.json else render(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
