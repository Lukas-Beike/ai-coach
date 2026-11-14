"""Classify a pull request's changed files for the test workflow.

On a pull request the checkout is GitHub's merge commit, whose first parent is
the base branch, so ``HEAD^1..HEAD`` is exactly the pull request's change.
``docs_only`` is true only when every changed path is documentation; the
workflow then skips the native, container, browser and quality suites and runs
the changed-test selection instead (#2747). ``ui`` is false only when no path
touches the user interface or the browser checks; the workflow then runs only
the desktop browser project, and mobile and tablet-landscape run on the
develop push (#2748). Any other event, a checkout that is not a merge commit, a
failed diff or an empty diff answers docs_only=false and ui=true: every suite
and every browser project runs.
"""

import os
import subprocess
import sys
from pathlib import PurePosixPath

DOC_SUFFIXES = (".md", ".txt")
DOC_FILES = frozenset({"README.md", "REVIEW.md", "AGENTS.md"})
DOC_TREES = ("docs/", ".agents/skills/", "openspec/")
# public/ ships in the image beside the served assets, so nothing there is docs.
NOT_DOC_TOP = frozenset({"public"})
# The client, its browser tests and their tooling, and the server code that
# serves the shell and assets (asset stamping, service worker, headers). A
# trailing slash marks a directory prefix; anything else is an exact path.
UI_PATHS = (
    "public/",
    "e2e/",
    "playwright.config.cjs",
    "package.json",
    "package-lock.json",
    "backend/http_api/static_assets.py",
    "scripts/run_browser_tests.py",
    "scripts/browser_environment.json",
    ".github/scripts/aggregate_browser_results.py",
    ".github/scripts/ci_changes.py",
    ".github/workflows/publish-container.yml",
)


def is_doc(path):
    parts = PurePosixPath(path).parts
    if not path.endswith(DOC_SUFFIXES) or "scripts" in parts:
        return False
    if path in DOC_FILES or path.startswith(DOC_TREES):
        return True
    return len(parts) == 2 and parts[1] == "AGENTS.md" and parts[0] not in NOT_DOC_TOP


def docs_only(paths):
    return bool(paths) and all(is_doc(path) for path in paths)


def touches_ui(path):
    return any(
        path.startswith(prefix) if prefix.endswith("/") else path == prefix
        for prefix in UI_PATHS
    )


def ui(paths):
    """Unknown or empty changes count as a UI change: every project runs."""
    return not paths or any(touches_ui(path) for path in paths)


def pull_request_paths(root="."):
    """The merge commit's change against its base parent, or None."""

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout

    try:
        if len(git("rev-list", "--parents", "-n", "1", "HEAD").split()) != 3:
            return None
        diff = git("diff", "--name-only", "--no-renames", "HEAD^1", "HEAD")
    except OSError, subprocess.CalledProcessError:
        return None
    return [line for line in diff.splitlines() if line]


def main():
    paths = None
    if os.environ.get("EVENT_NAME") == "pull_request":
        paths = pull_request_paths()
    values = {"docs_only": docs_only(paths or []), "ui": ui(paths)}
    if paths is None:
        print("Not a pull request merge commit: every suite runs.")
    else:
        print(f"{len(paths)} changed paths; docs_only={values['docs_only']}")
        for path in [path for path in paths if not is_doc(path)][:20]:
            print(f"  not documentation: {path}")
        print(f"ui={values['ui']}")
        for path in [path for path in paths if touches_ui(path)][:20]:
            print(f"  touches the UI: {path}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.writelines(
                f"{name}={str(value).lower()}\n" for name, value in values.items()
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
