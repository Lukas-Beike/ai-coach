"""Resolve one review thread on the agent's own pull request after it replied.

Athlete decision on #2629: the only GitHub write this script makes is the
`resolveReviewThread` GraphQL mutation, and only when the pull request was
authored by the authenticated `gh` user, the thread belongs to it and is still
unresolved, and the thread's last comment is that user's reply naming a commit
of the pull request (the fix SHA, 7 to 40 hex characters).

    python scripts/resolve_review_thread.py <pr> <thread-id>

Exit 0: resolved. 1: refused (the reason is printed). 2: bad input or a failed
`gh` call.
"""

from __future__ import annotations

import argparse
import re
import sys

from gh_cli import CliError, gh_json, positive_int

QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,"
    "name:$name){pullRequest(number:$number){author{login} "
    "commits(last:100){nodes{commit{oid}}} reviewThreads(first:100){nodes{id "
    "isResolved comments(last:20){nodes{author{login} body}}}}}}}"
)
# The one mutation this script may send (#2629).
MUTATION = (
    "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"
)
THREAD_ID = re.compile(r"PRRT_[A-Za-z0-9_-]+")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def refusal(pull: dict, viewer: str, thread_id: str) -> str | None:
    """Why this thread may not be resolved, or None when it may."""
    if (pull.get("author") or {}).get("login") != viewer:
        return "the pull request was not authored by the authenticated user"
    threads = pull["reviewThreads"]["nodes"]
    thread = next((item for item in threads if item["id"] == thread_id), None)
    if thread is None:
        return "the thread does not belong to this pull request"
    if thread["isResolved"]:
        return "the thread is already resolved"
    comments = thread["comments"]["nodes"]
    if len(comments) < 2 or (comments[-1]["author"] or {}).get("login") != viewer:
        return "the thread's last comment is not a reply by the authenticated user"
    commits = [node["commit"]["oid"] for node in pull["commits"]["nodes"]]
    named = SHA.findall(comments[-1]["body"])
    if not any(oid.startswith(sha) for sha in named for oid in commits):
        return "the reply names no commit of this pull request"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr", type=positive_int)
    parser.add_argument("thread")
    args = parser.parse_args(argv)
    if not THREAD_ID.fullmatch(args.thread):
        print("error: the thread id must look like PRRT_...", file=sys.stderr)
        return 2
    try:
        owner, name = gh_json("repo", "view", "--json", "nameWithOwner")[
            "nameWithOwner"
        ].split("/", 1)
        viewer = gh_json("api", "user")["login"]
        data = gh_json(
            "api",
            "graphql",
            "-f",
            f"query={QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={args.pr}",
        )
        pull = data["data"]["repository"]["pullRequest"]
        reason = refusal(pull, viewer, args.thread)
        if reason:
            print(f"refused: {reason}")
            return 1
        gh_json("api", "graphql", "-f", f"query={MUTATION}", "-f", f"id={args.thread}")
    except (CliError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"resolved {args.thread} on #{args.pr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
