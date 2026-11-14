"""Create a GitHub issue after a duplicate search; the body comes from a file.

    python scripts/issue_create.py --title "fix(sync): ..." --body-file body.md
        [--label bug] [--assignee @me] [--dry-run] [--force-new]

Exit 0: created (or dry run without a likely duplicate); 1: refused, a likely
duplicate exists (rerun with --force-new only after reading it); 2: bad input
or a failed gh call.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys

from gh_cli import CliError, gh, gh_json, read_body

TYPES = "build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test"
TITLE = re.compile(rf"^(?:{TYPES})(?:\([a-z0-9][a-z0-9-]*\))?!?: (?P<text>\S.*\S)$")
MAX_TITLE = 120
# Word-overlap score (0-1) of two titles: from DUPLICATE the issue is refused
# (exit 1) unless --force-new, from SIMILAR it is only listed.
DUPLICATE = 0.85
SIMILAR = 0.6
STOP_WORDS = frozenset(
    {"with", "from", "into", "that", "this", "when", "only", "the", "and"}
)


def title_text(title: str) -> str:
    """The description part of a Conventional Commit title, or a ValueError."""
    match = TITLE.match(title)
    if not match or len(title) > MAX_TITLE:
        raise ValueError(
            "title must be '<type>(<scope>): <description>' with a type from "
            f"{TYPES.replace('|', ', ')} and at most {MAX_TITLE} characters"
        )
    return match["text"]


def normalized(text: str) -> str:
    text = re.sub(rf"^(?:{TYPES})(?:\([^)]*\))?!?:\s*", "", text.strip().lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def keywords(text: str) -> list[str]:
    words = [w for w in normalized(text).split() if len(w) >= 4 and w not in STOP_WORDS]
    return sorted(set(words), key=lambda w: (-len(w), w))[:5]


def similar_issues(title: str, issues: list[dict]) -> list[tuple[float, dict]]:
    wanted = normalized(title)
    scored = []
    for issue in issues:
        score = difflib.SequenceMatcher(
            None, wanted, normalized(issue["title"])
        ).ratio()
        if score >= SIMILAR:
            scored.append((score, issue))
    return sorted(scored, key=lambda pair: -pair[0])


def search(title: str) -> list[dict]:
    words = keywords(title)
    if not words:
        return []
    found: dict[int, dict] = {}
    # One query per keyword pair keeps recall when the wording differs.
    for query in {" ".join(words[:2]), " ".join(words[:3]), words[0]}:
        for issue in gh_json(
            "issue", "list", "--state", "all", "--limit", "30",
            "--search", f"{query} in:title", "--json", "number,title,state,url",
        ):  # fmt: skip
            found[issue["number"]] = issue
    return list(found.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--assignee", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-new", action="store_true")
    args = parser.parse_args(argv)
    try:
        title_text(args.title)
        body_path = args.body_file
        read_body(body_path)
        candidates = similar_issues(args.title, search(args.title))
        for score, issue in candidates:
            print(
                f"similar {score:.2f}: #{issue['number']} {issue['state']} {issue['title']}"
            )
        if candidates and candidates[0][0] >= DUPLICATE and not args.force_new:
            print(
                "refused: a likely duplicate exists; update it, or rerun with --force-new"
            )
            return 1
        if args.dry_run:
            print("dry run: nothing created")
            return 0
        extra: list[str] = []
        for label in args.label:
            extra += ["--label", label]
        for assignee in args.assignee:
            extra += ["--assignee", assignee]
        url = gh(
            "issue", "create", "--title", args.title, "--body-file", body_path, *extra
        )
        print(f"created: {url.strip()}")
        return 0
    except (CliError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
