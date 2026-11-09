"""Worktree pruning checks with mocked git, gh and disk calls; nothing is removed."""

import importlib.util
import io
import subprocess
import tempfile
import unittest
from collections import namedtuple
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prune_worktrees", ROOT / "scripts/prune_worktrees.py"
)
assert SPEC is not None and SPEC.loader is not None
prune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune)

DAY = 86400
Usage = namedtuple("Usage", "total used free")


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FakeRepo:
    """Answers git/gh calls from a table; records every command."""

    def __init__(self, tmp, dirty=(), merged=(), pr_merged=(), remove_fails=()):
        self.tmp = Path(tmp)
        self.dirty, self.merged = set(dirty), set(merged)
        self.pr_merged, self.remove_fails = set(pr_merged), set(remove_fails)
        self.calls = []
        for name in ("primary", "current", "old", "dirty", "open", "pr"):
            (self.tmp / name).mkdir()

    def porcelain(self):
        rows = [
            ("primary", "develop"),
            ("current", "feat/current"),
            ("old", "feat/old"),
            ("dirty", "feat/dirty"),
            ("open", "feat/open"),
            ("pr", "feat/pr"),
        ]
        return "\n\n".join(
            f"worktree {self.tmp / d}\nHEAD abc\nbranch refs/heads/{b}\n"
            for d, b in rows
        )

    def git(self, *args, cwd=None):
        self.calls.append(("git", *args))
        if args[:2] == ("worktree", "list"):
            return done(self.porcelain())
        if args[0] == "rev-parse" and args[1] == "--show-toplevel":
            return done(str(self.tmp / "current"))
        if args[0] == "rev-parse":
            return done(str(Path(cwd) / ".git"))
        if args[0] == "status":
            return done(" M file\n" if Path(cwd).name in self.dirty else "")
        if args[0] == "merge-base":
            return done(code=0 if args[2] in self.merged else 1)
        if args[:2] == ("worktree", "remove"):
            bad = Path(args[2]).name in self.remove_fails
            return done(code=1 if bad else 0, stderr="contains changes\nmore")
        return done()

    def run(self, args, cwd=None):
        self.calls.append(tuple(args))
        listed = "[]"
        if args[0] == "gh" and args[args.index("--head") + 1] in self.pr_merged:
            listed = '[{"number": 5}]'
        return done(listed)

    def removed(self):
        return [c for c in self.calls if c[1:3] == ("worktree", "remove")]


class PruneWorktreesTests(unittest.TestCase):
    def run_main(self, repo, argv, free_gb=50, age_days=10):
        out, err = io.StringIO(), io.StringIO()
        patches = [
            mock.patch.object(prune, "git", repo.git),
            mock.patch.object(prune, "run", repo.run),
            mock.patch.object(prune, "last_modified", lambda _p: 1000.0),
            mock.patch.object(
                prune.shutil,
                "disk_usage",
                lambda _p: Usage(0, 0, int(free_gb * 1024**3)),
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with redirect_stdout(out), redirect_stderr(err):
            code = prune.main(argv, now=1000.0 + age_days * DAY)
        return code, out.getvalue(), err.getvalue()

    def make(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return FakeRepo(tmp.name, **kwargs)

    def test_parse_worktrees_reads_branch_detached_and_locked(self):
        text = (
            "worktree /a\nHEAD 1\nbranch refs/heads/develop\n\n"
            "worktree /b\nHEAD 2\ndetached\nlocked reason\n"
        )
        a, b = prune.parse_worktrees(text)
        self.assertEqual((a["path"], a["branch"]), ("/a", "develop"))
        self.assertTrue(b["detached"] and b["locked"] and b["branch"] is None)

    def test_dry_run_lists_candidates_and_removes_nothing(self):
        repo = self.make(
            dirty={"dirty"}, merged={"feat/old", "feat/dirty", "feat/current"}
        )
        code, out, _ = self.run_main(repo, [])
        self.assertEqual(code, 0)
        self.assertIn("prune  ", out)
        self.assertIn("feat/old", out.split("prune  ")[1])
        self.assertIn("uncommitted or untracked changes", out)
        self.assertIn("current worktree", out)
        self.assertIn("primary checkout", out)
        self.assertIn("branch not merged", out)
        self.assertEqual(repo.removed(), [])

    def test_apply_removes_without_force_and_deletes_branch(self):
        repo = self.make(merged={"feat/old"}, pr_merged={"feat/pr"})
        code, _out, _ = self.run_main(repo, ["--apply"])
        self.assertEqual(code, 0)
        removed = repo.removed()
        self.assertEqual(len(removed), 2)
        self.assertTrue(all("--force" not in c and "-f" not in c for c in removed))
        self.assertIn(("git", "branch", "-d", "feat/old"), repo.calls)
        self.assertIn(("git", "branch", "-D", "feat/pr"), repo.calls)
        for protected in ("feat/current", "feat/open", "feat/dirty", "develop"):
            self.assertNotIn(
                protected, [c[-1] for c in repo.calls if "branch" in c[:2]]
            )

    def test_recently_modified_worktree_is_kept(self):
        repo = self.make(merged={"feat/old"})
        _, out, _ = self.run_main(repo, ["--apply"], age_days=1)
        self.assertIn("modified 1.0 days ago", out)
        self.assertEqual(repo.removed(), [])
        _, out, _ = self.run_main(repo, ["--idle-days", "0.5"], age_days=1)
        self.assertIn("prune  ", out)

    def test_failed_remove_keeps_branch_and_exits_nonzero(self):
        repo = self.make(merged={"feat/old"}, remove_fails={"old"})
        code, out, _ = self.run_main(repo, ["--apply"])
        self.assertEqual(code, 1)
        self.assertIn("failed ", out)
        self.assertIn("contains changes", out)
        self.assertNotIn(("git", "branch", "-d", "feat/old"), repo.calls)

    def test_low_disk_space_warns_and_threshold_is_configurable(self):
        repo = self.make()
        _, out, err = self.run_main(repo, [], free_gb=2)
        self.assertIn("Free disk space: 2.0 GB", out)
        self.assertIn("WARNING: below 10 GB", err)
        _, _, err = self.run_main(repo, ["--min-free-gb", "1"], free_gb=2)
        self.assertEqual(err, "")

    def test_outside_a_repository_exits_nonzero(self):
        err = io.StringIO()
        with (
            mock.patch.object(prune, "git", lambda *a, **k: done(code=128)),
            redirect_stderr(err),
        ):
            self.assertEqual(prune.main([]), 1)
        self.assertIn("not inside a Git repository", err.getvalue())


if __name__ == "__main__":
    unittest.main()
