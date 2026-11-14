"""scripts/ci_run_stats.py with a stubbed GitHub CLI; no network."""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_run_stats
import gh_cli


def job(name, conclusion="success", queued="10:00:00", started="10:00:30"):
    return {
        "name": name,
        "conclusion": conclusion,
        "created_at": f"2026-11-14T{queued}Z",
        "started_at": f"2026-11-14T{started}Z",
    }


SHARDS = [f"Browser checks ({p} {n}/2)" for p in ("desktop", "mobile") for n in (1, 2)]
FULL = [job(n) for n in (*SHARDS, ci_run_stats.CONTAINER, "Browser checks")]
DESKTOP = [job(n) for n in (*SHARDS[:2], ci_run_stats.CONTAINER)] + [
    job(n, "skipped") for n in SHARDS[2:]
]
DOCS = [job("Test shard 1/4"), job(ci_run_stats.CONTAINER, "skipped")]
REUSED = [job(ci_run_stats.CONTAINER), job("Browser checks")]


def run(run_id, minutes, conclusion="success", created="10:00"):
    hour, minute = map(int, created.split(":"))
    end = hour * 60 + minute + minutes
    return {
        "id": run_id,
        "status": "completed",
        "conclusion": conclusion,
        "created_at": f"2026-11-14T{created}:00Z",
        "updated_at": f"2026-11-14T{end // 60:02d}:{end % 60:02d}:00Z",
    }


class CiRunStatsTests(unittest.TestCase):
    def test_p90_is_linear_interpolated_not_nearest_rank(self):
        # Inclusive method: 9 + 0.1 * (10 - 9) = 9.1; nearest rank would say 9.
        self.assertEqual(
            ci_run_stats.median_p90([float(n) for n in range(1, 11)]), (5.5, 9.1)
        )
        self.assertEqual(ci_run_stats.median_p90([4.0]), (4.0, 4.0))

    def test_run_type_comes_from_the_jobs_that_ran(self):
        for jobs, kind in (
            (FULL, "full"),
            (DESKTOP, "desktop-only"),
            (DOCS, "docs-only"),
            (REUSED, "other"),
            ([job("Browser checks (tablet-landscape)")], "full"),  # one shard
        ):
            with self.subTest(kind=kind):
                self.assertEqual(ci_run_stats.run_type(jobs), kind)

    def run_main(self, *extra, since="2026-11-14T09:00"):
        runs = [
            run(1, 10),
            run(2, 8),
            run(3, 2),
            run(4, 9, "failure"),  # counted only with --all-conclusions
            {**run(6, 140), "run_attempt": 2},  # a re-run two hours later
            {**run(7, 30, "failure"), "run_attempt": 2},  # dropped, not counted
            run(5, 7, created="11:30"),  # after the window
        ]
        jobs = {1: FULL, 2: DESKTOP, 3: DOCS, 6: FULL}
        paths = []

        def fake(argv, **_kwargs):
            path = argv[3]
            paths.append(path)
            if "/workflows/" in path:
                lines = runs
            else:
                lines = jobs[int(path.split("/runs/")[1].split("/")[0])]
            out = "\n".join(json.dumps(item) for item in lines)
            return subprocess.CompletedProcess(argv, 0, out, "")

        out = io.StringIO()
        with mock.patch.object(gh_cli.subprocess, "run", fake), redirect_stdout(out):
            code = ci_run_stats.main(
                ["--since", since, "--until", "2026-11-14T11:00", *extra]
            )
        return code, out.getvalue().splitlines(), paths

    def test_report_counts_successful_first_attempts_in_the_window_by_type(self):
        code, out, paths = self.run_main("--queue", "--first-attempts")
        self.assertEqual(code, 0)
        self.assertIn("event=pull_request", paths[0])
        self.assertIn("created=2026-11-14T09:00:00Z..2026-11-14T11:00:00Z", paths[0])
        self.assertEqual(
            out[1:],
            [
                "  re-run attempts left out: 1",
                "runs 3: median 8.0 min, p90 9.6 min",
                "  full: 1 runs, median 10.0 min, jobs per run 6-6",
                "  desktop-only: 1 runs, median 8.0 min, jobs per run 3-3",
                "  docs-only: 1 runs, median 2.0 min, jobs per run 1-1",
                "job queue: median 30 s, p90 30 s",
            ],
        )

    def test_reruns_count_by_default_and_are_reported(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("  re-run attempts included: 1", out)
        # 2, 8, 10, 140: median 9.0; p90 = 10 + 0.7 * 130 = 101.0
        self.assertIn("runs 4: median 9.0 min, p90 101.0 min", out)

    def test_all_conclusions_lists_them_and_types_only_successful_runs(self):
        code, out, paths = self.run_main("--all-conclusions", "--first-attempts")
        self.assertEqual(code, 0)
        self.assertIn("runs 4: median 8.5 min, p90 9.7 min", out)
        self.assertIn("  conclusions: failure 1, success 3", out)
        self.assertFalse([p for p in paths if "/runs/4/" in p])  # no type for it

    def test_offset_times_are_converted_and_an_empty_window_exits_1(self):
        # 10:00+01:00 is 09:00 UTC, the same window as above.
        _, _, paths = self.run_main(since="2026-11-14T10:00+01:00")
        self.assertIn("created=2026-11-14T09:00:00Z..", paths[0])
        code, out, _ = self.run_main(since="2026-11-14T10:59")
        self.assertEqual((code, out[-1]), (1, "no run in the window"))


if __name__ == "__main__":
    unittest.main()
