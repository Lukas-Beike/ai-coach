"""Isolated locked Playwright runner. --results-dir receives a unique run child.

Upload only that child's reports/manifest: authentication is held separately and
traces are disabled. Durations v1: {version:1, environment:{}, projects:{project:
{relative_spec:seconds}}}. Missing files use their project's frozen median or 1s.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "io.ai-coach.browser-run"
FAKE_PASSWORD = "e2e-fixture-password-1234"
MAX_JOBS = 2
# Chromium's error when the host ran out of socket buffers (seen on Windows Docker
# hosts). A child whose every failing test names it hit the machine's limits, not a
# test assertion; it is reported as an infrastructure error with a rerun hint.
HOST_NETWORK_ERROR = "net::ERR_NO_BUFFER_SPACE"


class RunnerError(Exception):
    """Safe diagnostics never contain child stdout or provider/environment text."""


def stamp():
    return datetime.now(UTC).isoformat()


def host_network_error(output):
    """Return the host network error when every failing test of a child names it.

    Only the per-test ``artifacts/*/error-context.md`` reports are read, symlinks
    are skipped, and only the fixed error name is returned, never report text. A
    child with any report that does not name the error failed an assertion.
    """
    reports = [
        report
        for report in sorted((Path(output) / "artifacts").glob("*/error-context.md"))
        if not report.is_symlink() and not report.parent.is_symlink()
    ]
    if not reports:
        return None
    for report in reports:
        try:
            text = report.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if HOST_NETWORK_ERROR not in text:
            return None
    return HOST_NETWORK_ERROR


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Evidence:
    def __init__(self, directory, run_id, args):
        self.directory = directory
        self.lock = threading.RLock()
        self.data = {
            "version": 1,
            "run_id": run_id,
            "started_at": stamp(),
            "status": "incomplete",
            "exit_code": None,
            "source": {},
            "inputs": {},
            "tools": {},
            "images": {},
            "cache_state": args.cache_state,
            "queue_seconds": None,
            "selection": {
                "project": args.project,
                "specs": args.spec,
                "shard": args.shard,
                "total": args.total,
                "mode": "complete"
                if args.project == "all" and not args.spec
                else "focused",
            },
            "resources": {"jobs": args.jobs, "playwright_workers": 1, "ports": []},
            "phases": {},
            "children": [],
            "cleanup_errors": [],
        }
        self.write()

    def write(self):
        with self.lock:
            atomic_json(self.directory / "manifest.json", self.data)

    def update(self, **values):
        with self.lock:
            self.data.update(values)
            self.write()

    def child(self, child, **values):
        with self.lock:
            child.update(values)
            self.write()

    @contextmanager
    def phase(self, name):
        start = time.monotonic()
        with self.lock:
            self.data["phases"][name] = {"started_at": stamp(), "status": "incomplete"}
            self.write()
        try:
            yield
        except BaseException:
            status = "failed"
            raise
        else:
            status = "completed"
        finally:
            with self.lock:
                self.data["phases"][name].update(
                    ended_at=stamp(), seconds=time.monotonic() - start, status=status
                )
                self.write()


class Processes:
    """Own groups; stop/reap children before cleaning observed Docker resources."""

    def __init__(self, stop=None):
        self.stop = stop or threading.Event()
        self.lock = threading.Lock()
        self.active = set()

    def run(
        self, command, *, cwd=ROOT, env=None, timeout=60, capture=True, cleanup=False
    ):
        if self.stop.is_set() and not cleanup:
            raise InterruptedError
        options = (
            {
                "creationflags": subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            }
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **options,
        )
        with self.lock:
            self.active.add(process)
        deadline = time.monotonic() + timeout if timeout is not None else None
        try:
            while True:
                try:
                    output, _ = process.communicate(timeout=0.2)
                    return process.returncode, (output or b"").decode(
                        "utf-8", errors="replace"
                    )
                except subprocess.TimeoutExpired:
                    if self.stop.is_set() and not cleanup:
                        raise InterruptedError
                    if deadline is not None and time.monotonic() >= deadline:
                        raise RunnerError(
                            "Child exceeded bounded startup/tool deadline"
                        )
        finally:
            if process.poll() is None:
                self.terminate(process)
            process.wait()
            with self.lock:
                self.active.discard(process)

    @staticmethod
    def terminate(process):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.wait()

    def stop_all(self):
        self.stop.set()
        with self.lock:
            children = list(self.active)
        for process in children:
            if process.poll() is None:
                self.terminate(process)


def checked(processes, command, **kwargs):
    code, output = processes.run(command, **kwargs)
    if code:
        raise RunnerError(f"Required tool/container command failed (exit {code})")
    return output


def toolchain(root):
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8-sig"))
    versions = {}
    for package in ("@playwright/test", "playwright", "playwright-core"):
        expected = lock["packages"]["node_modules/" + package]["version"]
        installed = root / "node_modules" / package / "package.json"
        if not installed.is_file():
            raise RunnerError(
                "Locked local Playwright missing; run npm ci --ignore-scripts"
            )
        observed = json.loads(installed.read_text(encoding="utf-8-sig"))["version"]
        if observed != expected:
            raise RunnerError("Installed Playwright differs from package-lock.json")
        versions[package] = observed
    node = shutil.which("node")
    if not node:
        raise RunnerError("Node is unavailable")
    return node, root / "node_modules/@playwright/test/cli.js", versions


def parse_listing(report):
    if report.get("errors"):
        raise RunnerError("Playwright listing failed")
    selected = {}

    def walk(suite):
        for spec in suite.get("specs", []):
            file = spec["file"].replace("\\", "/")
            if not file.startswith("e2e/"):
                file = "e2e/" + file
            if ".." in Path(file).parts or Path(file).is_absolute():
                raise RunnerError("Playwright listed an unexpected path")
            for test in spec.get("tests", []):
                project = test["projectName"]
                if not re.fullmatch(r"[a-z0-9-]+", project):
                    raise RunnerError("Playwright listed an unsafe project")
                identity = {
                    "id": spec["id"],
                    "project": project,
                    "project_id": test["projectId"],
                    "file": file,
                    "line": spec["line"],
                    "title": spec["title"],
                }
                selected.setdefault((project, file), []).append(identity)
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    return selected


def read_weights(path):
    if path is None or not path.exists():
        return {"version": 1, "environment": {}, "projects": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if (
            value["version"] != 1
            or not isinstance(value["projects"], dict)
            or not isinstance(value.get("environment", {}), dict)
        ):
            raise ValueError
        for project, weights in value["projects"].items():
            if not isinstance(project, str) or not isinstance(weights, dict):
                raise TypeError
            for file, weight in weights.items():
                if (
                    not isinstance(file, str)
                    or not file.startswith("e2e/")
                    or ".." in Path(file).parts
                ):
                    raise ValueError
                if (
                    isinstance(weight, bool)
                    or not isinstance(weight, (int, float))
                    or not math.isfinite(weight)
                    or weight <= 0
                ):
                    raise ValueError
    except ValueError, KeyError, TypeError:
        raise RunnerError("Malformed browser duration input") from None
    return value


def assign_files(files, weights, total):
    """LPT assignment: stable ties, frozen project median, otherwise one second."""
    fallback = statistics.median(weights.values()) if weights else 1.0
    bins, loads = [[] for _ in range(total)], [0.0] * total
    for file in sorted(files, key=lambda item: (-weights.get(item, fallback), item)):
        index = min(range(total), key=lambda slot: (loads[slot], slot))
        bins[index].append(file)
        loads[index] += weights.get(file, fallback)
    return bins


def select(listing, project, specs, shard, total, timing):
    if total < 1 or shard < 1 or shard > total:
        raise RunnerError("Require 1 <= shard <= total")
    projects = sorted({key[0] for key in listing})
    if project != "all":
        if project not in projects:
            raise RunnerError("Unknown or empty Playwright project")
        projects = [project]
    wanted = {item.replace("\\", "/").removeprefix("./") for item in specs}
    available = {file for name, file in listing if name in projects}
    if wanted - available:
        raise RunnerError("Requested spec absent from selected project listing")
    result = []
    for name in projects:
        files = {
            file
            for candidate, file in listing
            if candidate == name and (not wanted or file in wanted)
        }
        bins = assign_files(files, timing["projects"].get(name, {}), total)
        result.extend(
            {
                "project": name,
                "file": file,
                "identities": listing[name, file],
                "status": "pending",
                "exit_code": None,
                "phases": {},
            }
            for file in bins[shard - 1]
        )
    if not result:
        raise RunnerError("Selection/shard matches zero tests")
    return result


class Containers:
    def __init__(self, processes, private, run_id):
        self.processes, self.private, self.run_id = processes, private, run_id
        self.lock = threading.Lock()
        self.observed = set()
        self.cidfiles = []
        self.roles = {}
        self.cidroles = {}

    def create(self, name, arguments):
        cidfile = self.private / (name + ".cid")
        with self.lock:
            self.cidfiles.append(cidfile)
            self.cidroles[cidfile] = (
                2 if "-net-" in name else (1 if "-fixture-" in name else 0)
            )
        try:
            output = checked(
                self.processes,
                [
                    "docker",
                    "create",
                    "--name",
                    name,
                    "--label",
                    LABEL + "=" + self.run_id,
                    "--cidfile",
                    str(cidfile),
                    *arguments,
                ],
            )
            cid = output.strip()
            if not re.fullmatch(r"[a-f0-9]{64}", cid):
                raise RunnerError("Docker did not return a container identity")
            with self.lock:
                self.observed.add(cid)
                self.roles[cid] = self.cidroles[cidfile]
            return cid
        finally:
            self.collect_ids()

    def collect_ids(self):
        with self.lock:
            for path in self.cidfiles:
                if path.is_file():
                    cid = path.read_text(encoding="ascii").strip()
                    if re.fullmatch(r"[a-f0-9]{64}", cid):
                        self.observed.add(cid)
                        self.roles[cid] = self.cidroles[path]

    def remove(self, cid, *, cleanup=False):
        with self.lock:
            if cid not in self.observed:
                raise RunnerError("Refusing to clean an unobserved container")
        owner = checked(
            self.processes,
            [
                "docker",
                "inspect",
                "--format",
                '{{ index .Config.Labels "' + LABEL + '" }}',
                cid,
            ],
            cleanup=cleanup,
        ).strip()
        if owner != self.run_id:
            raise RunnerError("Refusing to clean a container with different ownership")
        checked(self.processes, ["docker", "rm", "--force", cid], cleanup=cleanup)
        with self.lock:
            self.observed.remove(cid)
            # Do not rediscover a successfully removed ID in the final CID-file sweep.
            for path in self.cidfiles:
                if path.is_file() and path.read_text(encoding="ascii").strip() == cid:
                    path.unlink()

    def cleanup(self):
        self.collect_ids()
        errors = []
        # Browser processes first, then fixtures, finally their network namespaces.
        for cid in sorted(
            self.observed, key=lambda item: (self.roles.get(item, 1), item)
        ):
            try:
                self.remove(cid, cleanup=True)
            except RunnerError, OSError:
                errors.append("Owned container cleanup failed")
        return errors


def image_identity(processes, image):
    info = json.loads(checked(processes, ["docker", "image", "inspect", image]))[0]
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", info["Id"]):
        raise RunnerError("Application/browser image identity unavailable")
    return info["Id"]


def reserve_ports(count):
    reservations = []
    try:
        for _ in range(count):
            sock = socket.socket()
            reservations.append(sock)
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
        return reservations
    except BaseException:
        for sock in reservations:
            sock.close()
        raise


def ready(port, stop, timeout=45):
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if stop.is_set():
            raise InterruptedError
        try:
            for path in ("/api/health", "/"):
                with opener.open(
                    f"http://127.0.0.1:{port}{path}", timeout=2
                ) as response:
                    if response.status != 200:
                        raise OSError
            return
        except OSError, urllib.error.URLError:
            stop.wait(0.5)
    raise RunnerError(
        "Disposable fixture failed bounded readiness; no fallback permitted"
    )


def browser_mounts(root):
    return [
        "--volume",
        str(root / "node_modules") + ":/work/node_modules:ro",
        "--volume",
        str(root / "e2e") + ":/work/e2e:ro",
        "--volume",
        str(root / "playwright.config.cjs") + ":/work/playwright.config.cjs:ro",
        "--volume",
        str(root / "public/index.html") + ":/work/public/index.html:ro",
        "--volume",
        str(root / "public/service-worker.js") + ":/work/public/service-worker.js:ro",
    ]


def browser_options(root, private):
    uid = os.getuid() or 1000
    gid = os.getgid() or 1000
    if os.getuid() == 0:
        os.chown(private, uid, gid)
    return [
        "--init",
        "--user",
        f"{uid}:{gid}",
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop=ALL",
        "--pids-limit=512",
        "--memory=2g",
        "--cpus=2",
        "--shm-size=1g",
        "--tmpfs",
        "/tmp:mode=1777",
        "--workdir",
        "/work",
        "--env",
        "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
        *browser_mounts(root),
    ]


def verify_browser(root, args, node, versions, processes, containers, private):
    browsers = json.loads(
        (root / "node_modules/playwright-core/browsers.json").read_text()
    )
    expected = {
        item["name"].replace("-", "_"): item["revision"]
        for item in browsers["browsers"]
        if item["name"] in ("chromium", "chromium-headless-shell")
    }
    script = """const fs=require('node:fs');const p=require('playwright-core');
const expected=JSON.parse(process.argv[1]);
for(const [name,revision] of Object.entries(expected)) {
 if(!fs.existsSync('/ms-playwright/'+name+'-'+revision))process.exit(2);
}
if(!fs.existsSync(p.chromium.executablePath()))process.exit(3);
console.log(JSON.stringify({revisions:expected,node:process.version}));"""
    if args.browser_image:
        if sys.platform != "linux":
            raise RunnerError(
                "--browser-image requires Linux host networking; use native browsers on Windows"
            )
        pinfile = root / "scripts/browser_environment.json"
        if not pinfile.is_file():
            raise RunnerError("Prepared browser environment definition missing")
        pin = json.loads(pinfile.read_text())
        if (
            pin.get("version") != versions["@playwright/test"]
            or pin.get("image") != args.browser_image
            or not re.search(r"@sha256:[a-f0-9]{64}$", args.browser_image)
        ):
            raise RunnerError("Prepared image differs from locked declared environment")
        image_id = image_identity(processes, args.browser_image)
        cid = containers.create(
            "acb-" + containers.run_id + "-verify",
            [
                "--network",
                "none",
                *browser_options(root, private),
                image_id,
                "node",
                "-e",
                script,
                json.dumps(expected),
            ],
        )
        code, output = processes.run(["docker", "start", "--attach", cid])
        exit_code = checked(
            processes, ["docker", "inspect", "--format", "{{.State.ExitCode}}", cid]
        ).strip()
        if code or exit_code != "0":
            raise RunnerError("Prepared browser revision check failed")
        observed = json.loads(output)
        if observed.get("revisions") != expected:
            raise RunnerError("Prepared browser revisions differ from locked package")
        containers.remove(cid)
        return {
            "mode": "prepared",
            "id": image_id,
            "digest": args.browser_image,
            "version": pin["version"],
            **observed,
        }
    native_script = """const fs=require('node:fs');const p=require('playwright-core');
if(!fs.existsSync(p.chromium.executablePath()))process.exit(2);
console.log(JSON.stringify({node:process.version}));"""
    observed = json.loads(checked(processes, [node, "-e", native_script]))
    return {"mode": "native", "revisions": expected, **observed}


class Execution:
    def __init__(
        self,
        root,
        args,
        evidence,
        processes,
        containers,
        private,
        image,
        browser,
        node,
        cli,
    ):
        self.root, self.args, self.evidence = root, args, evidence
        self.processes, self.containers, self.private = processes, containers, private
        self.image, self.browser, self.node, self.cli = image, browser, node, cli
        self.slots = []
        self.fixture_starts = {}

    def prepare_slots(self, count):
        reservations = reserve_ports(count * 2)
        try:
            for index, reservation in enumerate(reservations):
                port = reservation.getsockname()[1]
                name = f"acb-{self.containers.run_id}-net-{index}"
                cid = self.containers.create(
                    name,
                    [
                        "--publish",
                        f"127.0.0.1:{port}:8090",
                        "--no-healthcheck",
                        "--tmpfs",
                        "/data:uid=100,gid=101,mode=0700",
                        "--user",
                        "100:101",
                        "--read-only",
                        "--security-opt",
                        "no-new-privileges:true",
                        "--cap-drop=ALL",
                        "--pids-limit=16",
                        "--memory=32m",
                        "--cpus=0.1",
                        self.image,
                        "sleep",
                        "infinity",
                    ],
                )
                reservation.close()
                checked(self.processes, ["docker", "start", cid])
                self.slots.append((cid, port))
                self.evidence.data["resources"]["ports"].append(port)
                self.evidence.write()
            if sys.platform == "linux":
                for _ in range(50):
                    tentative = checked(
                        self.processes, ["ip", "-6", "address", "show", "tentative"]
                    )
                    if not tentative.strip():
                        break
                    if self.processes.stop.wait(0.2):
                        raise InterruptedError
                else:
                    raise RunnerError("Fixture network interfaces did not stabilize")
        finally:
            for reservation in reservations:
                reservation.close()

    def fixture(self, child, slot, index):
        start = time.monotonic()
        self.fixture_starts[id(child)] = start
        self.evidence.child(child, status="preparing", fixture_started_at=stamp())
        network, _ = self.slots[slot]
        cid = self.containers.create(
            f"acb-{self.containers.run_id}-fixture-{slot}-{index}",
            [
                "--network",
                "container:" + network,
                "--user",
                "100:101",
                "--read-only",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop=ALL",
                "--pids-limit=256",
                "--memory=1g",
                "--cpus=2",
                "--tmpfs",
                "/data:uid=100,gid=101,mode=0700",
                "--tmpfs",
                "/tmp",
                "--env",
                "APP_PASSWORD=" + FAKE_PASSWORD,
                "--env",
                "COOKIE_SECURE=false",
                "--env",
                "AI_COACH_DISPOSABLE_FIXTURE=1",
                "--volume",
                str(self.root / "e2e") + ":/app/e2e:ro",
                self.image,
                "python",
                "/app/e2e/fixture_runtime.py",
            ],
        )
        checked(self.processes, ["docker", "start", cid])
        self.evidence.child(
            child,
            status="prepared",
            phases={"fixture_start_seconds": time.monotonic() - start},
        )
        return cid

    def browser_command(self, child, port, output, private):
        prepared = self.args.browser_image is not None
        env = os.environ.copy()
        for key in list(env):
            if (
                key.startswith(("E2E_", "PLAYWRIGHT_"))
                and key != "PLAYWRIGHT_BROWSERS_PATH"
            ):
                del env[key]
        settings = {
            "E2E_BASE_URL": f"http://127.0.0.1:{port}",
            "E2E_APP_PASSWORD": FAKE_PASSWORD,
            "E2E_AUTH_STATE_PATH": "/private/state.json"
            if prepared
            else str(private / "state.json"),
            "E2E_PHASE_TIMINGS_PATH": "/private/phase.json"
            if prepared
            else str(private / "phase.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": "/results/report"
            if prepared
            else str(output / "report"),
        }
        # Playwright's file filter is a regex; escape/anchor the selected whole file.
        arguments = [
            "test",
            re.escape(child["file"]) + "$",
            "--project",
            child["project"],
            "--workers=1",
            "--trace=off",
            "--output",
            "/results/artifacts" if prepared else str(output / "artifacts"),
        ]
        if not prepared:
            env.update(settings)
            return [self.node, str(self.cli), *arguments], env, None
        options = [
            "--network",
            "host",
            *browser_options(self.root, private),
            "--volume",
            str(output) + ":/results",
            "--volume",
            str(private) + ":/private",
        ]
        if os.getuid() == 0:
            os.chown(output, 1000, 1000)
        if os.environ.get("CI"):
            settings["CI"] = os.environ["CI"]
        for key, value in settings.items():
            options.extend(["--env", key + "=" + value])
        cid = self.containers.create(
            f"acb-{self.containers.run_id}-browser-{uuid.uuid4().hex[:12]}",
            [
                *options,
                self.browser["id"],
                "node",
                "/work/node_modules/@playwright/test/cli.js",
                *arguments,
            ],
        )
        return ["docker", "start", "--attach", cid], env, cid

    def run_child(self, child, slot, fixture):
        evidence = self.evidence
        started = time.monotonic()
        name = (
            Path(child["file"]).name
            + "-"
            + hashlib.sha256(child["file"].encode()).hexdigest()[:10]
        )
        output = evidence.directory / child["project"] / name
        output.mkdir(parents=True, exist_ok=False)
        private = self.private / (child["project"] + "-" + name)
        private.mkdir(mode=0o700)
        evidence.child(
            child,
            status="running",
            started_at=stamp(),
            output=str(output.relative_to(evidence.directory)),
        )
        try:
            command, env, cid = self.browser_command(
                child, self.slots[slot][1], output, private
            )
            browser_started = time.monotonic()
            code, _ = self.processes.run(command, env=env, timeout=None, capture=False)
            if cid:
                code = (
                    int(
                        checked(
                            self.processes,
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{.State.ExitCode}}",
                                cid,
                            ],
                        )
                    )
                    or code
                )
                self.containers.remove(cid)
            browser_seconds = time.monotonic() - browser_started
            child["phases"]["browser_seconds"] = browser_seconds
            timing_path = private / "phase.json"
            if timing_path.is_file():
                try:
                    auth_seconds = json.loads(timing_path.read_text())[
                        "authentication_seconds"
                    ]
                    if (
                        type(auth_seconds) in (int, float)
                        and math.isfinite(auth_seconds)
                        and 0 <= auth_seconds <= browser_seconds
                    ):
                        child["phases"]["authentication_seconds"] = auth_seconds
                        child["phases"]["test_seconds"] = browser_seconds - auth_seconds
                except ValueError, KeyError, TypeError:
                    pass
            evidence.child(
                child, status="passed" if code == 0 else "failed", exit_code=code
            )
            (output / "process.txt").write_text(
                f"Playwright child exit code: {code}\n", encoding="utf-8"
            )
            if code:
                marker = host_network_error(output)
                if marker:
                    evidence.child(child, infrastructure_error=marker)
                    raise RunnerError(
                        f"Playwright child failed on a host network error ({marker}), "
                        "not a test assertion; rerun it with "
                        f"--project {child['project']} --spec {child['file']}"
                    )
                raise RunnerError(f"Playwright child failed (exit {code})")
            self.containers.remove(fixture)
        except BaseException as error:
            evidence.child(
                child,
                status="interrupted"
                if isinstance(error, (InterruptedError, KeyboardInterrupt))
                else "failed",
            )
            raise
        finally:
            evidence.child(
                child, ended_at=stamp(), elapsed_seconds=time.monotonic() - started
            )

    def lane(self, index, children):
        if not children:
            return
        try:
            current = self.fixture(children[0], index * 2, 0)
            for offset, child in enumerate(children):
                slot = index * 2 + offset % 2
                wait_started = time.monotonic()
                ready(self.slots[slot][1], self.processes.stop)
                child["phases"]["readiness_wait_seconds"] = (
                    time.monotonic() - wait_started
                )
                child["phases"]["fixture_ready_seconds"] = (
                    time.monotonic() - self.fixture_starts[id(child)]
                )
                self.evidence.child(child, fixture_ready_at=stamp())
                successor = None
                if offset + 1 < len(children):
                    successor = self.fixture(
                        children[offset + 1], index * 2 + (offset + 1) % 2, offset + 1
                    )
                self.run_child(child, slot, current)
                current = successor
        except BaseException as error:
            for child in children:
                if child["status"] in {"preparing", "prepared"}:
                    self.evidence.child(
                        child,
                        status="interrupted"
                        if isinstance(error, (InterruptedError, KeyboardInterrupt))
                        else "failed",
                    )
            raise

    def execute(self, children):
        jobs = min(self.args.jobs, len(children))
        self.prepare_slots(jobs)
        pool = ThreadPoolExecutor(max_workers=jobs)
        futures = []
        try:
            futures = [
                pool.submit(self.lane, index, children[index::jobs])
                for index in range(jobs)
            ]
            first_error = None
            while any(not future.done() for future in futures):
                for future in futures:
                    if future.done() and future.exception() is not None:
                        first_error = future.exception()
                        break
                if first_error:
                    break
                if self.processes.stop.wait(0.1):
                    raise InterruptedError
            if first_error:
                raise first_error
            for future in futures:
                future.result()
        except BaseException:
            self.processes.stop_all()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)


def parser():
    result = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    result.add_argument(
        "--project", required=True, help="exact configured project name, or all"
    )
    result.add_argument(
        "--spec",
        action="append",
        default=[],
        help="exact e2e-relative spec path; repeatable",
    )
    result.add_argument("--shard", type=int, default=1)
    result.add_argument("--total", type=int, default=1)
    result.add_argument("--jobs", type=int, choices=range(1, MAX_JOBS + 1), default=1)
    result.add_argument(
        "--image", default="ai-coach:e2e", help="already-built current-source app image"
    )
    result.add_argument(
        "--browser-image",
        help="prepared Linux image matching scripts/browser_environment.json",
    )
    result.add_argument(
        "--results-dir", type=Path, default=ROOT / "test-results/browser-runs"
    )
    result.add_argument(
        "--durations", type=Path, default=ROOT / "e2e/browser_durations.json"
    )
    result.add_argument(
        "--cache-state", choices=("cold", "warm", "unknown"), default="unknown"
    )
    result.add_argument(
        "--list",
        action="store_true",
        help="resolve identical selection without Docker/browser fixtures",
    )
    return result


def source_hashes(root, durations):
    # Hash source only, including helpers loaded while Playwright discovers files.
    # Keep auth state and other runtime files outside this explicit source allowlist.
    inputs = [
        root / item
        for item in (
            "scripts/run_browser_tests.py",
            "playwright.config.cjs",
            "public/index.html",
            "public/service-worker.js",
            "package.json",
            "package-lock.json",
            "scripts/browser_environment.json",
        )
    ]
    for pattern in ("*.js", "*.py", "helpers/**/*.js", "helpers/**/*.py"):
        inputs.extend(sorted((root / "e2e").glob(pattern)))
    inputs.append(durations)
    return {
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else "duration_input": hashlib.sha256(path.read_bytes()).hexdigest()
        for path in inputs
        if path.is_file()
    }


def main(argv=None):
    args = parser().parse_args(argv)
    run_id = uuid.uuid4().hex
    args.results_dir = args.results_dir.resolve()
    directory = args.results_dir / run_id
    directory.mkdir(parents=True, exist_ok=False)
    evidence = Evidence(directory, run_id, args)
    print(
        "Browser evidence: " + str(directory / "manifest.json"),
        file=sys.stderr,
        flush=True,
    )
    processes = Processes()
    started = time.monotonic()
    old_handlers = {}

    def interrupt(_signum, _frame):
        processes.stop.set()
        raise KeyboardInterrupt

    for number in (signal.SIGINT, signal.SIGTERM):
        old_handlers[number] = signal.signal(number, interrupt)
    code, containers = 1, None
    try:
        with tempfile.TemporaryDirectory(
            prefix="ai-coach-browser-private-"
        ) as private_name:
            private = Path(private_name)
            containers = Containers(processes, private, run_id)
            failure = None
            try:
                with evidence.phase("selection"):
                    node, cli, versions = toolchain(ROOT)
                    timing = read_weights(args.durations)
                    node_version = checked(processes, [node, "--version"]).strip()
                    listing = parse_listing(
                        json.loads(
                            checked(
                                processes,
                                [node, str(cli), "test", "--list", "--reporter=json"],
                            )
                        )
                    )
                    expected_identities = [
                        identity
                        for (project, _), values in sorted(listing.items())
                        if args.project == "all" or project == args.project
                        for identity in values
                    ]
                    children = select(
                        listing, args.project, args.spec, args.shard, args.total, timing
                    )
                    revision = checked(processes, ["git", "rev-parse", "HEAD"]).strip()
                    dirty = bool(
                        checked(
                            processes,
                            [
                                "git",
                                "status",
                                "--porcelain",
                                "--untracked-files=normal",
                            ],
                        ).strip()
                    )
                    hashes = source_hashes(ROOT, args.durations)
                    evidence.update(
                        source={"revision": revision, "dirty": dirty},
                        inputs=hashes,
                        selection={
                            **evidence.data["selection"],
                            "expected_identities": expected_identities,
                        },
                        tools={
                            "python": sys.version.split()[0],
                            "platform": sys.platform,
                            "node": node_version,
                            "packages": versions,
                        },
                        timing_input=timing,
                        children=children,
                    )
                if args.list:
                    evidence.update(status="listed", exit_code=0)
                    print(
                        json.dumps(
                            {
                                "version": 1,
                                "selection": evidence.data["selection"],
                                "children": children,
                            },
                            indent=2,
                        )
                    )
                    code = 0
                else:
                    with evidence.phase("prerequisites"):
                        image = image_identity(processes, args.image)
                        browser = verify_browser(
                            ROOT, args, node, versions, processes, containers, private
                        )
                        evidence.update(
                            images={"application": image, "browser": browser}
                        )
                    with evidence.phase("execution"):
                        Execution(
                            ROOT,
                            args,
                            evidence,
                            processes,
                            containers,
                            private,
                            image,
                            browser,
                            node,
                            cli,
                        ).execute(children)
                    if not all(child["status"] == "passed" for child in children):
                        raise RunnerError("Required children did not all complete")
                    code = 0
            except BaseException as error:
                failure = error
                evidence.update(
                    error=str(error)
                    if isinstance(error, RunnerError)
                    else type(error).__name__
                )
                raise
            finally:
                errors = []
                try:
                    with evidence.phase("cleanup"):
                        processes.stop_all()
                        errors = containers.cleanup()
                except BaseException as error:
                    # Preserve a pending failure; otherwise propagate only safe diagnostics.
                    errors = ["Owned resource cleanup failed"]
                    if failure is None:
                        if isinstance(error, (KeyboardInterrupt, InterruptedError)):
                            raise
                        raise RunnerError("Owned resource cleanup failed") from None
                finally:
                    if errors and code == 0:
                        code = 1
                    evidence.update(
                        cleanup_errors=errors,
                        resources={
                            **evidence.data["resources"],
                            "containers_not_confirmed_removed": sorted(
                                containers.observed
                            ),
                            "cleanup_confirmed": not errors and not containers.observed,
                        },
                    )
    except KeyboardInterrupt, InterruptedError:
        code = 130
        evidence.update(status="interrupted", error="Run interrupted")
    except RunnerError, OSError, ValueError, KeyError, TypeError:
        code = code or 1
        evidence.update(status="failed")
    finally:
        for number, handler in old_handlers.items():
            signal.signal(number, handler)
        if evidence.data["status"] != "interrupted":
            evidence.data["status"] = (
                "listed"
                if args.list and code == 0
                else ("passed" if code == 0 else "failed")
            )
        evidence.update(
            exit_code=code,
            ended_at=stamp(),
            wall_seconds=time.monotonic() - started,
            child_seconds=sum(
                child.get("elapsed_seconds", 0) for child in evidence.data["children"]
            ),
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
