"""scripts/release_dispatch.py and scripts/image_verify.py with fakes; no network."""

import io
import json
import subprocess
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gh_cli
import image_verify
import release_dispatch

V = "2.1.2"
VERSION_PR = {
    "number": 1, "title": f"chore(release): set application version to {V}",
    "state": "MERGED", "mergedAt": "x", "createdAt": "2026-11-11T10:00:00Z", "url": "u",
}  # fmt: skip
PROMOTION_PR = {
    "number": 2, "title": f"chore(release): promote {V} to main",
    "state": "MERGED", "mergedAt": "x", "createdAt": "2026-11-11T10:05:00Z", "url": "u",
}  # fmt: skip


def fake_gh(prs, release=None, publish=()):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        args = argv[1:]
        if args[:2] == ["pr", "list"]:
            base = args[args.index("--base") + 1]
            data = [p for p in prs if ("promote" in p["title"]) == (base == "main")]
        elif args[:2] == ["release", "view"]:
            if release is None:
                return subprocess.CompletedProcess(argv, 1, "", "release not found")
            data = release
        elif args[:2] == ["run", "list"]:
            data = list(publish)
        elif args[:2] == ["workflow", "run"]:
            data = None
        else:
            return subprocess.CompletedProcess(argv, 1, "", "unexpected")
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    return run, calls


def follow(*args, **fakes):
    run, calls = fake_gh(**fakes)
    out = io.StringIO()
    with mock.patch.object(gh_cli.subprocess, "run", run), redirect_stdout(out):
        code = release_dispatch.main(["follow", *args])
    return code, out.getvalue(), calls


class ReleaseDispatchTests(unittest.TestCase):
    def test_complete_chain_is_published(self):
        code, out, calls = follow(
            "--version", V,
            prs=[VERSION_PR, PROMOTION_PR],
            release={"tagName": V, "isDraft": False, "targetCommitish": "abc123"},
            publish=[{"databaseId": 9, "status": "completed", "conclusion": "success", "headBranch": V, "url": "u"}],
        )  # fmt: skip
        self.assertEqual(code, 0, out)
        self.assertIn("ok version PR #1 MERGED", out)
        self.assertIn("ok promotion PR #2 MERGED", out)
        self.assertIn(f"ok release {V} published", out)
        self.assertIn("ok publish run 9 success", out)
        for call in calls:
            self.assertNotIn("merge", call[1:3])

    def test_pending_and_failed_links(self):
        code, out, _ = follow("--version", V, prs=[VERSION_PR])
        self.assertEqual(code, 3)
        self.assertIn("pending promotion PR not created yet", out)
        self.assertIn("pending release", out)
        closed = dict(PROMOTION_PR, state="CLOSED")
        code, out, _ = follow("--version", V, prs=[VERSION_PR, closed])
        self.assertEqual(code, 1)
        self.assertIn("failed promotion PR #2 CLOSED", out)

    def test_follow_finds_the_version_from_the_newest_version_pr(self):
        code, out, _ = follow("--since", "2026-11-11T09:00:00Z", prs=[VERSION_PR])
        self.assertIn("ok version PR #1 MERGED", out)
        code, out, _ = follow("--since", "2026-11-12T00:00:00Z", prs=[VERSION_PR])
        self.assertEqual(code, 3)
        self.assertIn("none found yet", out)

    def test_dispatch_passes_the_version_and_rejects_bad_ones(self):
        run, calls = fake_gh(prs=[])
        with (
            mock.patch.object(gh_cli.subprocess, "run", run),
            redirect_stdout(io.StringIO()),
            mock.patch.object(release_dispatch.time, "sleep"),
        ):
            release_dispatch.main(["dispatch", "--version", V])
        self.assertEqual(
            calls[0][1:],
            [
                "workflow",
                "run",
                "daily-release.yml",
                "--ref",
                "develop",
                "-f",
                f"release_version={V}",
            ],
        )
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            release_dispatch.main(["dispatch", "--version", "v2.1"])


class FakeResponse(io.BytesIO):
    def __init__(self, status, headers, body=b""):
        super().__init__(body)
        self.status, self.headers = status, headers

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def registry(digests):
    def urlopen(request, timeout):
        url = request.full_url
        if "/token?" in url:
            return FakeResponse(200, {}, json.dumps({"token": "anon"}).encode())
        tag = url.rsplit("/", 1)[1]
        if tag not in digests:
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO())
        return FakeResponse(200, {"Docker-Content-Digest": digests[tag]})

    return urlopen


A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


class ImageVerifyTests(unittest.TestCase):
    def verify(self, digests, *args):
        out = io.StringIO()
        with (
            mock.patch.object(
                image_verify.urllib.request, "urlopen", registry(digests)
            ),
            redirect_stdout(out),
        ):
            code = image_verify.main(["--tag", V, *args])
        return code, out.getvalue()

    def test_matching_tag_latest_and_running_digest(self):
        code, out = self.verify({V: A, "latest": A}, "--running", A)
        self.assertEqual(code, 0, out)
        self.assertIn(f"ok {V} {A}", out)

    def test_mismatch_missing_tag_and_wrong_running_digest(self):
        for digests, args, expect in (
            ({V: A, "latest": B}, (), f"FAIL latest {B}"),
            ({"latest": A}, (), f"FAIL {V} missing"),
            ({V: A, "latest": A}, ("--running", B), f"FAIL running {B}"),
        ):
            with self.subTest(expect=expect):
                code, out = self.verify(digests, *args)
                self.assertEqual(code, 1)
                self.assertIn(expect, out)


if __name__ == "__main__":
    unittest.main()
