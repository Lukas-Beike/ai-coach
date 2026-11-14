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
        ):
            with self.subTest(kind=kind):
                self.assertEqual(ci_run_stats.run_type(jobs), kind)

    def test_report_counts_successful_runs_in_the_window_by_type(self):
        runs = [
            run(1, 10),
            run(2, 8),
            run(3, 2),
            run(4, 9, "failure"),  # not counted without --all-conclusions
            run(5, 7, created="11:30"),  # after the window
        ]
        jobs = {1: FULL, 2: DESKTOP, 3: DOCS}

        def fake(argv, **_kwargs):
            path = argv[3]
            if "/workflows/" in path:
                self.assertIn("event=pull_request", path)
                lines = runs
            else:
                lines = jobs[int(path.split("/runs/")[1].split("/")[0])]
            out = "\n".join(json.dumps(item) for item in lines)
            return subprocess.CompletedProcess(argv, 0, out, "")

        out = io.StringIO()
        with mock.patch.object(gh_cli.subprocess, "run", fake), redirect_stdout(out):
            code = ci_run_stats.main(
                [
                    "--since",
                    "2026-11-14T09:00",
                    "--until",
                    "2026-11-14T11:00",
                    "--queue",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue().splitlines()[1:],
            [
                "runs 3: median 8.0 min, p90 9.6 min",
                "  full: 1 runs, median 10.0 min, jobs per run 6-6",
                "  desktop-only: 1 runs, median 8.0 min, jobs per run 3-3",
                "  docs-only: 1 runs, median 2.0 min, jobs per run 1-1",
                "job queue: median 30 s, p90 30 s",
            ],
        )


if __name__ == "__main__":
    unittest.main()
