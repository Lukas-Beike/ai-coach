"""scripts/branch_sync.py against temporary git repositories; no network."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import branch_sync
from gh_cli import CliError

SONAR_NAME = "sonar.cmd" if os.name == "nt" else "sonar"


def git(cwd, *args):
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def commit(repo, name, text, subject):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", subject)


def make_sonar(directory):
    directory.mkdir(parents=True)
    tool = directory / SONAR_NAME
    tool.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n")
    tool.chmod(0o755)


class BranchSyncTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        git(self.root, "init", "-q", "--bare", "-b", "develop", str(self.origin))
        git(self.root, "init", "-q", "-b", "develop", str(self.work))
        for key, value in (
            ("user.name", "Test"),
            ("user.email", "test@example.test"),
            ("commit.gpgsign", "false"),
        ):
            git(self.work, "config", key, value)
        git(self.work, "remote", "add", "origin", str(self.origin))
        commit(self.work, "a.txt", "one\n", "chore: base")
        git(self.work, "push", "-q", "-u", "origin", "develop")
        git(self.work, "checkout", "-q", "-b", "feat/x")
        previous = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def advance_develop(self, name="b.txt", text="two\n"):
        git(self.work, "checkout", "-q", "develop")
        commit(self.work, name, text, "chore: advance develop")
        git(self.work, "push", "-q", "origin", "develop")
        git(self.work, "reset", "-q", "--hard", "HEAD~1")
        git(self.work, "checkout", "-q", "feat/x")

    def sync(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = branch_sync.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_refuses_protected_and_detached_heads(self):
        git(self.work, "checkout", "-q", "develop")
        code, out, _ = self.sync()
        self.assertEqual((code, "refused: on develop" in out), (1, True))
        git(self.work, "checkout", "-q", "--detach")
        code, out, _ = self.sync()
        self.assertEqual((code, "detached HEAD" in out), (1, True))

    def test_refuses_a_dirty_tree_before_touching_anything(self):
        (self.work / "a.txt").write_text("dirty\n", encoding="utf-8")
        code, out, _ = self.sync()
        self.assertEqual((code, "uncommitted changes" in out), (1, True))

    def test_rebases_onto_the_fetched_target_and_reports_counts(self):
        commit(self.work, "c.txt", "mine\n", "feat(ui): add c")
        self.advance_develop()
        code, out, err = self.sync()
        self.assertEqual((code, err), (0, ""))
        self.assertRegex(out, r"head [0-9a-f]+ on feat/x: ahead 1, behind 0")
        self.assertTrue((self.work / "b.txt").exists())
        self.assertEqual(git(self.work, "log", "-1", "--format=%s"), "feat(ui): add c")

    def test_conflict_stays_in_progress_and_lists_files(self):
        commit(self.work, "a.txt", "mine\n", "fix: mine")
        self.advance_develop("a.txt", "theirs\n")
        code, out, _ = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("a.txt", out)
        self.assertIn("git rebase --abort", out)
        self.assertTrue((self.work / ".git" / "rebase-merge").exists())

    def test_lists_invalid_subjects(self):
        commit(self.work, "c.txt", "1\n", "wip stuff")
        commit(self.work, "d.txt", "2\n", "feat(UI): bad scope")
        commit(self.work, "e.txt", "3\n", "fix(sync)!: fine")
        code, out, _ = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("wip stuff", out)
        self.assertIn("feat(UI): bad scope", out)
        self.assertNotIn("fix(sync)!", out)

    def test_push_uses_hooks_and_force_with_lease(self):
        hooks = self.work / ".githooks"
        hooks.mkdir()
        (hooks / "pre-push").write_text(
            "#!/bin/sh\ntouch hook-ran\n", encoding="utf-8", newline="\n"
        )
        (hooks / "pre-push").chmod(0o755)
        git(self.work, "add", ".githooks")
        git(self.work, "commit", "-q", "-m", "chore: add hook")
        with mock.patch.object(branch_sync, "push_env", return_value=dict(os.environ)):
            code, out, err = self.sync("--push")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("pushed: feat/x", out)
        self.assertEqual(
            git(self.origin, "rev-parse", "feat/x"), git(self.work, "rev-parse", "HEAD")
        )
        self.assertTrue((self.work / "hook-ran").exists())

        (hooks / "pre-push").write_text(
            "#!/bin/sh\necho 'Push blocked: the quality ratchet could not run' >&2\nexit 1\n",
            encoding="utf-8",
            newline="\n",
        )
        git(self.work, "commit", "-q", "-am", "chore: refusing hook")
        with mock.patch.object(branch_sync, "push_env", return_value=dict(os.environ)):
            code, _, err = self.sync("--push")
        self.assertEqual(code, 2)
        self.assertIn("failed to push", err)
        self.assertIn("Push blocked: the quality ratchet could not run", err)

    def test_push_keeps_remote_work_the_branch_has_not_seen(self):
        commit(self.work, "c.txt", "1\n", "feat(ui): add c")
        git(self.work, "push", "-q", "-u", "origin", "feat/x")
        other = self.root / "other"
        git(self.root, "clone", "-q", "-b", "feat/x", str(self.origin), str(other))
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.test")
        commit(other, "d.txt", "2\n", "feat(ui): remote only")
        git(other, "push", "-q", "origin", "feat/x")
        remote_tip = git(self.origin, "rev-parse", "feat/x")
        git(self.work, "commit", "-q", "--amend", "-m", "feat(ui): add c, reworded")
        with mock.patch.object(branch_sync, "push_env", return_value=dict(os.environ)):
            code, _, err = self.sync("--push", "--allow-root", "c.txt")
        self.assertEqual(code, 2)
        self.assertIn("rejected", err)
        self.assertEqual(git(self.origin, "rev-parse", "feat/x"), remote_tip)

    def test_invalid_subject_blocks_the_push(self):
        commit(self.work, "c.txt", "1\n", "wip")
        with mock.patch.object(branch_sync, "push_env", return_value=dict(os.environ)):
            code, _, _ = self.sync("--push")
        self.assertEqual(code, 1)
        self.assertEqual(git(self.origin, "branch", "--list", "feat/x"), "")

    def test_new_root_file_blocks_the_push_unless_allowed(self):
        commit(self.work, "stray-redirect", "temp path\n", "fix(ui): add file")
        with mock.patch.object(branch_sync, "push_env", return_value=dict(os.environ)):
            code, out, _ = self.sync("--push")
            self.assertEqual(code, 1)
            self.assertIn("  stray-redirect", out)
            self.assertEqual(git(self.origin, "branch", "--list", "feat/x"), "")
            code, out, _ = self.sync("--push", "--allow-root", "stray-redirect")
        self.assertEqual(code, 0)
        self.assertIn("pushed: feat/x", out)

    def test_push_without_sonar_exits_two_before_any_git_change(self):
        empty = self.root / "empty"
        empty.mkdir()
        with (
            mock.patch.object(branch_sync, "sonar_dirs", return_value=[empty]),
            mock.patch.object(branch_sync.shutil, "which", return_value=None),
        ):
            code, _out, err = self.sync("--push")
        self.assertEqual(code, 2)
        self.assertIn("SonarQube CLI", err)
        self.assertEqual(git(self.origin, "branch", "--list", "feat/x"), "")


class SonarLookupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.base = {"PATH": str(Path(tmp.name) / "empty")}

    def test_leaves_the_environment_alone_when_sonar_is_on_path(self):
        make_sonar(self.home / "tools")
        env = {"PATH": str(self.home / "tools")}
        self.assertEqual(branch_sync.push_env(env, self.home), env)

    def test_prepends_the_first_known_install_directory(self):
        local = self.home / "AppData" / "sonarqube-cli" / "bin"
        make_sonar(local)
        make_sonar(self.home / ".local" / "bin")
        env = {**self.base, "LOCALAPPDATA": str(self.home / "AppData")}
        result = branch_sync.push_env(env, self.home)
        self.assertEqual(result["PATH"], f"{local}{os.pathsep}{self.base['PATH']}")
        self.assertEqual(env["PATH"], self.base["PATH"])

    def test_finds_the_home_directories(self):
        for parts in ((".sonar", "sonarqube-cli", "bin"), (".local", "bin")):
            with self.subTest(parts=parts):
                directory = self.home.joinpath(*parts)
                make_sonar(directory)
                result = branch_sync.push_env(self.base, self.home)
                self.assertTrue(result["PATH"].startswith(str(directory)))
                (directory / SONAR_NAME).unlink()

    def test_missing_cli_names_the_prerequisite(self):
        with self.assertRaisesRegex(CliError, "needs the SonarQube CLI"):
            branch_sync.push_env(self.base, self.home)


if __name__ == "__main__":
    unittest.main()
