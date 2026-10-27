"""Supervise isolated local SQLCipher shards; no network or live data mounts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "ai-coach.local-tests"
# Keep this explicit: never mount a repository root, .env, or persistent data.
INPUTS = (
    "tests",
    "Dockerfile",
    "requirements.in",
    "requirements.txt",
    "requirements-dev.in",
    "requirements-dev.txt",
    "requirements-graphify.in",
    "requirements-graphify.txt",
    "run-server.ps1",
    "backend",
    "AGENTS.md",
    "REVIEW.md",
    ".agents",
    ".codex/hooks.json",
    ".claude/settings.json",
    "pyproject.toml",
    "README.md",
    "docs",
    "public",
    "server.py",
    "playwright.config.cjs",
    "e2e",
    ".github",
    "tools",
    "scripts",
)
# Tests use /app/tests so their path setup cannot shadow the built application
# with /review source mounts. Runtime sources always come from the fresh image.
IMAGE_INPUTS = ("server.py", "backend", "public", "requirements.txt")
EXTRA_MOUNTS = tuple(
    (relative, f"/app/{relative}")
    for relative in INPUTS
    if relative not in IMAGE_INPUTS
)


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def hidden():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def source_identity(root):
    # Hash only declared source inputs, including untracked source; never secrets.
    allowed = (*INPUTS, "garmin-login.py", ".dockerignore")
    listing = (
        subprocess.check_output(
            ["git", "ls-files", "-co", "--exclude-standard", "-z", "--", *allowed],
            cwd=root,
            **hidden(),
        )
        .decode()
        .split("\0")
    )
    digest = hashlib.sha256()
    for relative in sorted(set(listing) - {""}):
        path = root / relative
        if path.is_symlink():
            raise ValueError("source symlinks are not supported")
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
    revision = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, **hidden())
        .decode()
        .strip()
    )
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", *allowed],
        cwd=root,
        **hidden(),
    )
    return {
        "revision": revision,
        "dirty": bool(dirty),
        "source_sha256": digest.hexdigest(),
    }


def coverage_wheel(path, root):
    """Accept only an offline wheel whose hash is in the locked dev requirements."""
    content = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    block = re.search(
        r"(?m)^coverage==([^\s\\]+)(.*?)(?=^[A-Za-z0-9_-]+==|\Z)", content, re.DOTALL
    )
    if block is None or not path.name.startswith(f"coverage-{block[1]}-"):
        raise ValueError("coverage wheel must match requirements-dev.txt")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest not in re.findall(r"--hash=sha256:([a-f0-9]{64})", block[2]):
        raise ValueError("coverage wheel hash is absent from requirements-dev.txt")
    return digest


def validate_selection(plans):
    if not plans:
        raise ValueError("missing selection evidence")
    discovered = plans[0]["discovered_ids"]
    all_ids, classes = [], set()
    for index, plan in enumerate(plans, 1):
        if (
            plan["status"] != "selected"
            or plan["shard"] != index
            or plan["total"] != len(plans)
            or plan["suite"] != "all"
            or plan["discovered_ids"] != discovered
            or plan["suite_ids"] != discovered
            or not plan["selected_ids"]
        ):
            raise ValueError("inconsistent shard selection")
        selected_classes = set(plan["selected_classes"])
        if classes & selected_classes:
            raise ValueError("a test class was split across shards")
        classes.update(selected_classes)
        all_ids.extend(plan["selected_ids"])
    if len(all_ids) != len(set(all_ids)) or sorted(all_ids) != sorted(discovered):
        raise ValueError(
            "shards do not partition the discovered selection exactly once"
        )


def validate_result(plan, result):
    for key in (
        "discovered_ids",
        "suite_ids",
        "selected_ids",
        "selected_classes",
        "suite",
        "shard",
        "total",
    ):
        if result.get(key) != plan[key]:
            raise ValueError(f"shard result changed {key}")
    if (
        result.get("status") != "passed"
        or result.get("errors")
        or result.get("failures")
    ):
        raise ValueError("shard tests failed or did not finish")
    # A class-level skip has no startTest calls; report actual counts without
    # mistaking setUpClass errors for successfully executed test methods.
    if result.get("tests_run") != len(result.get("executed_ids", [])):
        raise ValueError("inconsistent executed test count")


class Supervisor:
    def __init__(self, args, root=ROOT):
        self.args, self.root = args, root
        self.run_id = uuid.uuid4().hex
        base = args.results_dir or Path(tempfile.gettempdir()) / "ai-coach-tests"
        base.mkdir(parents=True, exist_ok=True)
        self.output = base.resolve() / self.run_id
        self.output.mkdir()
        self.processes = []
        self.containers = []
        self.summary = {
            "version": 1,
            "run_id": self.run_id,
            "status": "preparing",
            "selection_mode": "complete",
            "workers": args.workers,
            "selection_status": "pending_discovery",
            "cache_state": args.cache_state,
            "phases": {},
            "shards": [],
            "tools": {"host_python": platform.python_version()},
            "requested_image": args.image,
            "started": time.time(),
        }
        self.save()
        print(f"SQLCipher results: {self.output}", flush=True)

    def save(self):
        atomic_json(self.output / "summary.json", self.summary)

    def spawn(self, command, name):
        log = (self.output / f"{name}.log").open("wb")
        try:
            process = subprocess.Popen(
                command, cwd=self.root, stdout=log, stderr=subprocess.STDOUT, **hidden()
            )
        finally:
            log.close()
        self.processes.append(process)
        return process

    def command(self, command, name):
        started = time.time()
        self.summary["phases"][name] = {"started": started, "status": "running"}
        self.save()
        code = self.spawn(command, name).wait()
        self.summary["phases"][name].update(
            ended=time.time(),
            exit_code=code,
            status="passed" if code == 0 else "failed",
        )
        self.save()
        if code:
            raise RuntimeError(f"{name} failed ({code}); see {name}.log")

    def prepare_test_image(self, image):
        # Only this small test-only definition is sent to the networked build.
        # No source, live state, or optional wheel belongs in its build context.
        context = self.output / "preparation"
        context.mkdir()
        shutil.copyfile(
            self.root / "scripts/Dockerfile.sqlcipher-tests", context / "Dockerfile"
        )
        iid = self.output / "test-image.id"
        self.command(
            [
                "docker",
                "build",
                "--build-arg",
                f"APP_IMAGE={self.args.image.split('@', 1)[0]}@{image}",
                "--iidfile",
                str(iid),
                str(context),
            ],
            "prepare-test-image",
        )
        prepared = iid.read_text().strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", prepared):
            raise ValueError("missing prepared test image identity")
        self.summary["test_image"] = prepared
        self.save()
        return prepared

    def check_prerequisites(self, image):
        script = (
            "import importlib.util,os,pathlib,subprocess; "
            "assert os.geteuid() == 100, 'tests must run as app'; "
            "assert pathlib.Path(importlib.util.find_spec('server').origin) == "
            "pathlib.Path('/app/server.py'), 'server must come from app image'; "
            "assert pathlib.Path(importlib.util.find_spec('backend').origin) == "
            "pathlib.Path('/app/backend/__init__.py'), 'backend must come from app image'; "
            f"inputs={INPUTS!r}; "
            "assert all((pathlib.Path('/review') / p).exists() for p in inputs), "
            "'missing read-only review input'; "
            "assert all((pathlib.Path('/app') / p).exists() for p in inputs), "
            "'missing test input'; "
            "assert not any((pathlib.Path('/review') / p).exists() "
            "for p in ('.git','.env','data')), 'unexpected runtime input'; "
            "subprocess.run(['git','--version'],check=True)"
        )
        self.command(
            self.container(
                "prerequisites", self.output, ["python", "-c", script], image
            ),
            "prerequisites",
        )

    def container(self, name, output, command, image, *, coverage=False):
        cid = self.output / f"{name}.cid"
        self.containers.append(cid)
        args = [
            "docker",
            "run",
            "--name",
            f"coach-tests-{self.run_id}-{name}",
            "--cidfile",
            str(cid),
            "--label",
            f"{LABEL}={self.run_id}",
            "--read-only",
            "--network",
            "none",
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop=ALL",
            "--pids-limit=256",
            "--memory=512m",
            "--cpus=1",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/data",
            "--workdir",
            "/app",
            "--env",
            "PYTHONPATH=/coverage-tool:/app:/app/tests",
            "--env",
            "COVERAGE_FILE=/output/.coverage",
        ]
        for relative in INPUTS:
            args += ["--volume", f"{self.root / relative}:/review/{relative}:ro"]
        for relative, target in EXTRA_MOUNTS:
            args += ["--volume", f"{self.root / relative}:{target}:ro"]
        args += ["--volume", f"{output}:/output"]
        if coverage:
            wheel = self.args.coverage_wheel.resolve()
            args += [
                "--volume",
                f"{wheel}:/wheels/{wheel.name}:ro",
                "--tmpfs",
                "/coverage-tool",
            ]
            # pip is preparation only, offline and hash-verified by the host.
            script = (
                "import subprocess,sys; "
                f"subprocess.run([sys.executable,'-m','pip','install','--no-index',"
                f"'--no-deps','--target','/coverage-tool',{('/wheels/' + wheel.name)!r}],check=True); "
                f"sys.exit(subprocess.call({command!r}))"
            )
            command = ["python", "-c", script]
        return [*args, image, *command]

    def cleanup(self):
        # Reap ALL host children before attempting removal of observed containers.
        errors = []
        for process in self.processes:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            except OSError, subprocess.SubprocessError:
                errors.append("child could not be reaped; container cleanup deferred")
        if errors:
            self.summary["cleanup_errors"] = errors
            return False
        for cidfile in self.containers:
            if not cidfile.exists():
                continue
            cid = cidfile.read_text().strip()
            if not re.fullmatch(r"[a-f0-9]{64}", cid):
                errors.append("invalid container identity")
                continue
            try:
                observed = (
                    subprocess.check_output(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            '{{index .Config.Labels "' + LABEL + '"}}',
                            cid,
                        ],
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                        **hidden(),
                    )
                    .decode()
                    .strip()
                )
                if observed != self.run_id:
                    raise RuntimeError("container ownership mismatch")
                subprocess.run(
                    ["docker", "rm", "-f", cid],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    **hidden(),
                )
            except OSError, subprocess.SubprocessError, RuntimeError:
                errors.append("owned container cleanup failed")
        self.summary["cleanup_errors"] = errors
        return not errors

    def execute(self):
        code = 1
        try:
            self.summary["source"] = source_identity(self.root)
            self.save()
            self.command(
                [
                    "docker",
                    "version",
                    "--format",
                    "{{.Client.Version}}/{{.Server.Version}}",
                ],
                "docker-version",
            )
            self.summary["tools"]["docker"] = (
                (self.output / "docker-version.log").read_text().strip()
            )
            if self.args.coverage_wheel:
                self.summary["coverage_wheel_sha256"] = coverage_wheel(
                    self.args.coverage_wheel, self.root
                )
            iid = self.output / "image.id"
            self.command(
                [
                    "docker",
                    "build",
                    "--tag",
                    self.args.image,
                    "--iidfile",
                    str(iid),
                    str(self.root),
                ],
                "build",
            )
            image = iid.read_text().strip()
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                raise ValueError("missing current image identity")
            self.summary["image"] = image
            image = self.prepare_test_image(image)
            self.check_prerequisites(image)
            plans = []
            for index in range(1, self.args.workers + 1):
                output = self.output / f"shard-{index}"
                output.mkdir()
                # The image runs as uid 100, including on native Linux hosts.
                output.chmod(0o777)
                command = [
                    "python",
                    "/app/tests/run_tests.py",
                    "--shard",
                    str(index),
                    "--total",
                    str(self.args.workers),
                    "--list",
                    "--result-json",
                    "/output/selection.json",
                ]
                self.command(
                    self.container(f"list-{index}", output, command, image),
                    f"list-{index}",
                )
                plans.append(json.loads((output / "selection.json").read_text()))
                self.summary["shards"].append(
                    {"selection": plans[-1], "status": "pending"}
                )
                self.save()
            validate_selection(plans)
            self.summary["shards"] = [
                {"selection": plan, "status": "pending"} for plan in plans
            ]
            self.summary["status"] = "running"
            self.summary["selection_status"] = "partition_verified"
            self.save()
            children = []
            for index in range(1, self.args.workers + 1):
                output = self.output / f"shard-{index}"
                runner = [
                    "/app/tests/run_tests.py",
                    "--shard",
                    str(index),
                    "--total",
                    str(self.args.workers),
                    "--result-json",
                    "/output/result.json",
                ]
                if self.args.record_durations_directory:
                    runner += ["--record-durations", "/output/test_durations.json"]
                command = [
                    "python",
                    *(
                        ["-m", "coverage", "run", "--rcfile=/review/pyproject.toml"]
                        if self.args.coverage_wheel
                        else []
                    ),
                    *runner,
                ]
                child = self.spawn(
                    self.container(
                        f"test-{index}",
                        output,
                        command,
                        image,
                        coverage=bool(self.args.coverage_wheel),
                    ),
                    f"test-{index}",
                )
                children.append(child)
                self.summary["shards"][index - 1].update(
                    status="running", started=time.time()
                )
                self.save()
            pending = set(range(len(children)))
            while pending:
                for offset in sorted(pending):
                    exit_code = children[offset].poll()
                    if exit_code is None:
                        continue
                    item = self.summary["shards"][offset]
                    item.update(exit_code=exit_code, ended=time.time(), status="failed")
                    result_path = self.output / f"shard-{offset + 1}" / "result.json"
                    try:
                        result = json.loads(result_path.read_text())
                        item["result"] = result
                        validate_result(plans[offset], result)
                        if exit_code == 0:
                            item["status"] = "passed"
                    except OSError, ValueError, KeyError:
                        item["evidence_error"] = (
                            "missing, failed, or inconsistent result"
                        )
                    pending.remove(offset)
                    self.save()
                if pending:
                    time.sleep(0.1)
            if any(item["status"] != "passed" for item in self.summary["shards"]):
                raise RuntimeError(
                    "one or more shards failed or lack complete evidence"
                )
            if self.args.coverage_wheel:
                self.combine_coverage(image)
            if source_identity(self.root) != self.summary["source"]:
                raise RuntimeError("source changed during validation")
            if self.args.record_durations_directory:
                recording = json.loads(
                    (self.output / "shard-1/test_durations.json").read_text()
                )
                atomic_json(
                    self.args.record_durations_directory / "test_durations.json",
                    recording,
                )
            self.summary["status"] = "passed"
            code = 0
        except KeyboardInterrupt:
            self.summary["status"] = "interrupted"
        except (
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            subprocess.SubprocessError,
        ) as error:
            self.summary.update(status="failed", error=str(error))
            print(str(error), file=sys.stderr)
        finally:
            if not self.cleanup():
                if code == 0:
                    self.summary["status"] = "cleanup_failed"
                code = 1
            self.summary["ended"] = time.time()
            self.save()
        return code

    def combine_coverage(self, image):
        files = []
        for index in range(1, self.args.workers + 1):
            outputs = list((self.output / f"shard-{index}").glob(".coverage.*"))
            if len(outputs) != 1 or outputs[0].stat().st_size == 0:
                raise ValueError("missing or ambiguous shard coverage")
            files.append(f"/results/shard-{index}/{outputs[0].name}")
        output = self.output / "coverage"
        output.mkdir()
        output.chmod(0o777)
        command = ["python", "-m", "coverage", "combine", "--keep", *files]
        args = self.container("coverage", output, command, image, coverage=True)
        args[args.index(image) : args.index(image)] = [
            "--volume",
            f"{self.output}:/results:ro",
        ]
        self.command(args, "coverage-combine")
        if not (output / ".coverage").is_file():
            raise ValueError("coverage combine produced no data")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="ai-coach:local")
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, 5),
        default=1,
        help="bounded processes: 1 default, 2 first benchmark, at most 4",
    )
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--record-durations-directory", type=Path)
    parser.add_argument(
        "--coverage-wheel",
        type=Path,
        help="offline Linux wheel matching the hash-locked dev coverage pin",
    )
    parser.add_argument(
        "--cache-state", choices=("cold", "warm", "unknown"), default="unknown"
    )
    args = parser.parse_args(argv)
    if args.record_durations_directory and (
        args.workers != 1 or not args.record_durations_directory.is_dir()
    ):
        parser.error(
            "duration recording requires one worker and an existing destination directory"
        )
    if args.coverage_wheel and (
        not args.coverage_wheel.is_file() or args.coverage_wheel.suffix != ".whl"
    ):
        parser.error("--coverage-wheel needs an existing offline wheel")
    return args


def main():
    args = parse_args()
    previous = signal.signal(
        signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    try:
        return Supervisor(args).execute()
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
