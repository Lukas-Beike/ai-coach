"""Find a complete, green test run of this source tree to reuse (#2749).

The release chain tests one tree several times: the develop push of the
version commit, the promotion pull request, the main push and the release
event all carry the same tree. A run may skip the native shards, the browser
matrix and the quality job only when an earlier run of this workflow, started
by a push to develop or main of this repository, tested the identical tree,
succeeded, and ran every suite itself (a run that reused another is no
evidence). An earlier trusted run of the same tree that is still running is
awaited. Any other case, and any failed lookup, runs the full suite.
"""

import json
import os
import subprocess
import sys
import time

WORKFLOW = "publish-container.yml"
TRUSTED_BRANCHES = ("develop", "main")
BROWSER_PROJECTS = ("mobile", "tablet-landscape", "desktop")
BROWSER_SHARDS = 2
WAIT_SECONDS = 45 * 60
POLL_SECONDS = 30
# Push runs per branch searched; a release chain spans far fewer.
RUNS_PER_BRANCH = 100
CALL_TIMEOUT = 60
RUNNING = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


def required_jobs(native_shards):
    """Job name -> step that must have succeeded in it (None: the job alone)."""
    jobs = {
        f"Test shard {shard}/{native_shards}": "Run unit tests"
        for shard in range(1, native_shards + 1)
    }
    for project in BROWSER_PROJECTS:
        for shard in range(1, BROWSER_SHARDS + 1):
            jobs[f"Browser checks ({project} {shard}/{BROWSER_SHARDS})"] = None
    for name in (
        "Container unit tests",
        "test",
        "Incremental quality checks",
        "Browser checks",
    ):
        jobs[name] = None
    return jobs


def trusted(run, repository):
    return (
        run.get("event") == "push"
        and run.get("head_branch") in TRUSTED_BRANCHES
        and (run.get("head_repository") or {}).get("full_name") == repository
    )


def complete(jobs, native_shards):
    """True when every suite ran and passed in the run these jobs belong to."""
    by_name = {job["name"]: job for job in jobs}
    for name, step in required_jobs(native_shards).items():
        job = by_name.get(name)
        if not job or job.get("conclusion") != "success":
            return False
        if step and not any(
            item.get("name") == step and item.get("conclusion") == "success"
            for item in job.get("steps") or []
        ):
            return False
    return True


def tree_of(run):
    return (run.get("head_commit") or {}).get("tree_id")


def choose(own_tree, own_run_id, runs, jobs_of, repository, native_shards):
    """Return (run id or None, reason, ids of earlier same-tree runs still running)."""
    candidates = [
        run
        for run in runs
        if run["id"] < own_run_id
        and trusted(run, repository)
        and tree_of(run) == own_tree
    ]
    running = sorted(run["id"] for run in candidates if run["status"] in RUNNING)
    for run in sorted(candidates, key=lambda item: item["id"], reverse=True):
        if run["status"] != "completed" or run.get("conclusion") != "success":
            continue
        if complete(jobs_of(run["id"]), native_shards):
            return run["id"], f"run {run['id']} ({run['head_branch']} push)", running
    searched = f"{len(runs)} develop and main push runs searched"
    return None, f"no complete green run of this tree ({searched})", running


class GitHub:
    def __init__(self, repository):
        self.repository = repository
        self.jobs = {}

    def api(self, path):
        output = subprocess.run(
            ["gh", "api", "-X", "GET", f"repos/{self.repository}/{path}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT,
        ).stdout
        return json.loads(output)

    def runs(self):
        found = []
        for branch in TRUSTED_BRANCHES:
            found += self.api(
                f"actions/workflows/{WORKFLOW}/runs?event=push&branch={branch}"
                f"&per_page={RUNS_PER_BRANCH}"
            )["workflow_runs"]
        return found

    def jobs_of(self, run_id):
        """Jobs of a completed run; they no longer change, so fetch them once."""
        if run_id not in self.jobs:
            self.jobs[run_id] = self.api(f"actions/runs/{run_id}/jobs?per_page=100")[
                "jobs"
            ]
        return self.jobs[run_id]


def decide(
    github,
    own_tree,
    own_run_id,
    native_shards,
    wait=WAIT_SECONDS,
    sleep=time.sleep,
    clock=time.monotonic,
):
    deadline = clock() + wait
    while True:
        run_id, reason, running = choose(
            own_tree,
            own_run_id,
            github.runs(),
            github.jobs_of,
            github.repository,
            native_shards,
        )
        if run_id or not running:
            return run_id, reason
        if clock() >= deadline:
            return None, f"earlier runs {running} still running after {wait} s"
        print(f"Waiting for earlier runs of this tree: {running}", flush=True)
        sleep(POLL_SECONDS)


def main():
    own_tree = ""
    try:
        own_tree = subprocess.run(
            ["git", "rev-parse", f"{os.environ['SOURCE_SHA']}^{{tree}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT,
        ).stdout.strip()
        run_id, reason = decide(
            GitHub(os.environ["REPOSITORY"]),
            own_tree,
            int(os.environ["RUN_ID"]),
            int(os.environ["PYTHON_TEST_SHARDS"]),
        )
    # Any failure, an unexpected API shape included, runs the full suite.
    except Exception as error:  # noqa: BLE001
        run_id, reason = None, f"lookup failed ({type(error).__name__})"
    if run_id:
        print(f"Reusing {reason}: tree {own_tree} already passed every suite.")
    else:
        print(f"Full suite: {reason}.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"reuse_run={run_id or ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
