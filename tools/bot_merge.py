"""Attempt protected merges for eligible bot PRs using trusted GitHub metadata."""

import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def eligible(pr, repository):
    if (
        pr.get("state") != "open"
        or pr.get("draft") is not False
        or not pr.get("auto_merge")
    ):
        return False
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if (head.get("repo") or {}).get("full_name") != repository:
        return False
    author = (pr.get("user") or {}).get("login")
    if author == "dependabot[bot]":
        return base.get("ref") == "develop"
    if author != "ai-coach-release-bot[bot]":
        return False
    patterns = {
        "develop": r"chore/release-version-\d+\.\d+\.\d+",
        "main": r"chore/release-promotion-\d+\.\d+\.\d+",
    }
    return bool(
        re.fullmatch(patterns.get(base.get("ref"), r"(?!)"), head.get("ref", ""))
    )


def request(path, token, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(
        "https://api.github.com/" + path,
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="PUT" if body is not None else "GET",
    )
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def release_test_passed(pr, repository, token):
    revisions = (pr["head"]["sha"], pr.get("merge_commit_sha"))
    for revision in dict.fromkeys(revisions):
        if not revision:
            continue
        if revision != pr["head"]["sha"]:
            commit = request(f"repos/{repository}/git/commits/{revision}", token)
            parents = [parent.get("sha") for parent in commit.get("parents", [])]
            if parents != [pr["base"]["sha"], pr["head"]["sha"]]:
                continue
        checks = request(
            f"repos/{repository}/commits/{revision}/check-runs?check_name=test&per_page=100",
            token,
        )
        if any(
            check.get("name") == "test"
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
            and (check.get("app") or {}).get("id") == 15368
            for check in checks.get("check_runs", [])
        ):
            return True
    return False


def run(repository, token):
    page = 1
    numbers = []
    while True:
        prs = request(
            f"repos/{repository}/pulls?state=open&per_page=100&page={page}", token
        )
        if not prs:
            break
        numbers.extend(pr["number"] for pr in prs)
        page += 1
    for number in numbers:
        try:
            pr = request(f"repos/{repository}/pulls/{number}", token)
            if not eligible(pr, repository):
                continue
            sha = pr["head"]["sha"]
            if pr["user"][
                "login"
            ] == "ai-coach-release-bot[bot]" and not release_test_passed(
                pr, repository, token
            ):
                continue
            result = request(
                f"repos/{repository}/pulls/{number}/merge",
                token,
                {"sha": sha, "merge_method": "squash"},
            )
            if result.get("merged") is not True:
                raise RuntimeError(f"GitHub did not confirm merge of PR #{number}")
            print(f"Merged PR #{number}.")
        except HTTPError as error:
            error.close()
            if error.code not in (404, 405, 409, 422):
                raise
            print(f"PR #{number} is not mergeable yet (HTTP {error.code}).")


if __name__ == "__main__":
    try:
        run(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"Bot merge failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
