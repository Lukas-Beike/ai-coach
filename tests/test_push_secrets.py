import contextlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_push_secrets as scan


class PushSecretTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.enterContext(contextlib.chdir(self.root))
        scan.git("init", "-q")
        scan.git("config", "user.name", "Synthetic")
        scan.git("config", "user.email", "synthetic@example.invalid")

    def commit(self, content):
        (self.root / "fixture.py").write_text(content)
        scan.git("add", ".")
        scan.git("commit", "-qm", "synthetic")
        return scan.git("rev-parse", "HEAD").decode().strip()

    def update(self, local, remote="0" * 40):
        return f"refs/heads/test {local} refs/heads/test {remote}\n"

    def test_intermediate_deleted_content_is_checked(self):
        base = self.commit("base")
        middle = self.commit("synthetic forbidden marker")
        tip = self.commit("clean")
        middle_blob = scan.git("rev-parse", middle + ":fixture.py").decode().strip()
        self.assertIn(middle_blob, scan.outgoing_objects(self.update(tip, base)))
        run = subprocess.run

        def scanner(command, **kwargs):
            if command[0] == "synthetic-sonar":
                contents = [Path(p).read_bytes() for p in command[3:]]
                self.assertTrue(any(b"forbidden marker" in c for c in contents))
                self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
                return subprocess.CompletedProcess(command, 1)
            return run(command, **kwargs)

        with (
            patch.object(scan.shutil, "which", return_value="synthetic-sonar"),
            patch.object(scan.subprocess, "run", side_effect=scanner),
            self.assertRaises(RuntimeError),
        ):
            scan.check(self.update(tip, base))
        self.assertEqual((self.root / "fixture.py").read_text(), "clean")

    def test_new_branch_includes_history_and_deduplicates_refs(self):
        base = self.commit("old")
        tip = self.commit("new")
        objects = scan.outgoing_objects(self.update(tip))
        self.assertIn(
            scan.git("rev-parse", base + ":fixture.py").decode().strip(), objects
        )
        self.assertEqual(objects, scan.outgoing_objects(self.update(tip) * 2))

    def test_missing_scanner_blocks_push(self):
        tip = self.commit("clean")
        with (
            patch.object(scan.shutil, "which", return_value=None),
            self.assertRaises(RuntimeError),
        ):
            scan.check(self.update(tip))

    def test_unknown_remote_tip_still_scans_outgoing_history(self):
        base = self.commit("old")
        tip = self.commit("new")
        objects = scan.outgoing_objects(self.update(tip, "f" * 40))
        self.assertIn(
            scan.git("rev-parse", base + ":fixture.py").decode().strip(), objects
        )
        self.assertIn(
            scan.git("rev-parse", tip + ":fixture.py").decode().strip(), objects
        )

    def test_malformed_object_ids_are_rejected_before_any_git_call(self):
        valid = "a" * 40
        for local, remote in (
            ("--synthetic-option", valid),
            (valid, "--synthetic-option"),
            ("a" * 39, valid),
            (valid, "g" * 40),
            ("0" * 40, "invalid"),
        ):
            with (
                self.subTest(local=local, remote=remote),
                patch.object(scan, "git", side_effect=AssertionError("Git called")),
                patch.object(
                    scan.subprocess, "run", side_effect=AssertionError("Git called")
                ),
                self.assertRaises(ValueError),
            ):
                scan.outgoing_objects(self.update(local, remote))

    def test_deleted_ref_and_noop_do_not_require_scanner(self):
        tip = self.commit("clean")
        with patch.object(scan.shutil, "which", side_effect=AssertionError("scanner")):
            self.assertEqual(scan.check(self.update("0" * 40, tip)), 0)
            self.assertEqual(scan.check(self.update(tip, tip)), 0)

    def test_untouched_lines_of_an_edited_file_are_not_rescanned(self):
        base = self.commit("synthetic flagged line\nkept\n")
        tip = self.commit("synthetic flagged line\nkept\nadded clean line\n")
        joined = b"\n".join(self.scanned_by(self.update(tip, base)))
        self.assertIn(b"added clean line", joined)
        self.assertNotIn(b"synthetic flagged line", joined)

    def scanned_by(self, updates):
        run = subprocess.run
        scanned = []

        def scanner(command, **kwargs):
            if command[0] == "synthetic-sonar":
                scanned.extend(Path(p).read_bytes() for p in command[3:])
                return subprocess.CompletedProcess(command, 0)
            return run(command, **kwargs)

        with (
            patch.object(scan.shutil, "which", return_value="synthetic-sonar"),
            patch.object(scan.subprocess, "run", side_effect=scanner),
        ):
            scan.check(updates)
        return scanned

    def test_added_runs_keep_order_and_plus_prefixed_content(self):
        base = self.commit("keep\n")
        tip = self.commit("keep\nBEGIN\n++body\nBEGIN\nEND\n")
        scanned = self.scanned_by(self.update(tip, base))
        self.assertIn(b"BEGIN\n++body\nBEGIN\nEND", scanned)

    def test_new_and_binary_files_are_scanned_whole(self):
        base = self.commit("keep\n")
        (self.root / "new.txt").write_text("fresh line\nsecond\n")
        (self.root / "blob.bin").write_bytes(b"\x00\x01binary secret\x00")
        scan.git("add", ".")
        scan.git("commit", "-qm", "files")
        tip = scan.git("rev-parse", "HEAD").decode().strip()
        scanned = self.scanned_by(self.update(tip, base))
        self.assertIn(b"fresh line\nsecond\n", scanned)
        self.assertIn(b"\x00\x01binary secret\x00", scanned)

    def test_merged_base_lines_are_not_rescanned(self):
        self.commit("keep\n")
        scan.git("branch", "-m", "base")
        scan.git("checkout", "-qb", "feature")
        self.commit("keep\nfeature line\n")
        scan.git("checkout", "-q", "base")
        pushed = self.commit("keep\nsynthetic flagged base line\n")
        scan.git("update-ref", "refs/remotes/origin/base", pushed)
        scan.git("checkout", "-q", "feature")
        scan.git("merge", "-q", "--no-edit", "-X", "ours", "base")
        tip = scan.git("rev-parse", "HEAD").decode().strip()
        joined = b"\n".join(self.scanned_by(self.update(tip, "f" * 40)))
        self.assertNotIn(b"synthetic flagged base line", joined)

    def test_merge_resolution_content_is_scanned(self):
        self.commit("keep\n")
        scan.git("branch", "-m", "base")
        scan.git("checkout", "-qb", "feature")
        self.commit("keep\nfeature line\n")
        scan.git("checkout", "-q", "base")
        self.commit("keep\nbase line\n")
        scan.git("checkout", "-q", "feature")
        scan.git("merge", "-q", "--no-commit", "-X", "ours", "base")
        (self.root / "fixture.py").write_text("keep\nresolution only line\n")
        scan.git("commit", "-qam", "merge")
        tip = scan.git("rev-parse", "HEAD").decode().strip()
        remote = scan.git("rev-parse", "HEAD^1").decode().strip()
        joined = b"\n".join(self.scanned_by(self.update(tip, remote)))
        self.assertIn(b"resolution only line", joined)

    def test_clean_push_scans_committed_content_not_dirty_worktree(self):
        tip = self.commit("committed clean")
        (self.root / "fixture.py").write_text("uncommitted private data")
        scanned = self.scanned_by(self.update(tip))
        self.assertIn(b"committed clean", scanned)
        self.assertNotIn(b"uncommitted private data", scanned)


if __name__ == "__main__":
    unittest.main()
