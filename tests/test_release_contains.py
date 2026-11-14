"""scripts/release_contains.py on a synthetic squash-promote history; no network."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_contains

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,  # no signing or hooks from the host
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args, day=1):
    date = f"2026-01-{day:02d}T12:00:00Z"
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env={**ENV, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        check=True,
    )
    return done.stdout.strip()


def commit(repo, day, name, text=None):
    """Commit a write (or, without text, the removal) of one file on `day`."""
    if text is None:
        git(repo, "rm", "-q", name)
    else:
        (Path(repo) / name).write_text(text, encoding="utf-8")
        git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"change {name}", day=day)
    return git(repo, "rev-parse", "HEAD")


class ReleaseContainsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = self.repo = Path(tmp.name)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, 1, "app.txt", "v0\n")
        git(repo, "switch", "-q", "-c", "develop")
        self.fix = commit(repo, 2, "fix.txt", "fix\n")
        version = commit(repo, 3, "app.txt", "v1\n")
        # Squash promote: main gets a new commit carrying develop's tree.
        git(repo, "switch", "-q", "main")
        tree = git(repo, "rev-parse", f"{version}^{{tree}}")
        promote = git(repo, "commit-tree", tree, "-p", "HEAD", "-m", "promote", day=4)
        git(repo, "update-ref", "refs/heads/main", promote)
        git(repo, "tag", "-a", "-m", "release", "1.0.0", promote)
        git(repo, "switch", "-q", "develop")
        self.later = commit(repo, 5, "later.txt", "later\n")
        commit(repo, 6, "later.txt")  # the revert brings the release tree back

    def run_script(self, *args):
        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = release_contains.main([*args, "--branch", "develop"])
        finally:
            os.chdir(cwd)
        return code, out.getvalue() + err.getvalue()

    def test_squash_promoted_commit_is_contained_and_a_later_one_is_not(self):
        # Plain ancestry says no: the tag is not on develop's history.
        with self.assertRaises(subprocess.CalledProcessError):
            git(self.repo, "merge-base", "--is-ancestor", self.fix, "1.0.0")
        code, out = self.run_script(self.fix, "1.0.0")
        self.assertEqual(code, 0, out)
        self.assertIn("contained in 1.0.0", out)
        # The later revert restores the release tree, but after the tag.
        code, out = self.run_script(self.later, "1.0.0")
        self.assertEqual(code, 1, out)
        self.assertIn("not contained in 1.0.0", out)

    def test_a_tag_on_the_branch_history_needs_no_tree_match(self):
        git(self.repo, "tag", "on-develop", self.later)
        self.assertEqual(self.run_script(self.fix, "on-develop")[0], 0)

    def test_unknown_commit_or_tree_is_an_error(self):
        self.assertEqual(self.run_script("0" * 40, "1.0.0")[0], 2)
        git(self.repo, "switch", "-q", "-c", "side", "main")
        side = commit(self.repo, 7, "side.txt", "never on develop\n")
        git(self.repo, "tag", "orphan", side)
        code, out = self.run_script(self.fix, "orphan")
        self.assertEqual(code, 2)
        self.assertIn("no develop commit has the tree of orphan", out)


if __name__ == "__main__":
    unittest.main()
