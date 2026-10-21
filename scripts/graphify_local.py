"""Explicit, isolated, secret-scanned local Graphify integration."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

VERSION = "0.9.93"
WRAPPER_SCHEMA = 4
TIMEOUT = 180
EXTENSIONS = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".ps1",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".properties",
}
SOURCE_DIRS = {"backend", "public", "scripts", "tests", "e2e", ".github", ".agents"}
ROOT_FILES = {
    "server.py",
    "pyproject.toml",
    "pytest.ini",
    "ruff.toml",
    "package.json",
    "requirements.in",
    "requirements-dev.in",
    "sonar-project.properties",
    "requirements.txt",
    "setup.cfg",
    "tox.ini",
    "Dockerfile",
}
DENIED = {
    ".git",
    ".graphify-local",
    "graphify-out",
    "data",
    "backup",
    "backups",
    "tokens",
    "token",
    "credentials",
    "credential",
    "secrets",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    "runtime",
    "logs",
    "recovery",
    ".claude",
    ".codex",
    ".pytest_cache",
}


class Unavailable(RuntimeError):
    pass


def repo_root(start: Path | None = None) -> Path:
    result = subprocess.run(
        [
            "git",
            "-C",
            str((start or Path.cwd()).resolve()),
            "rev-parse",
            "--show-toplevel",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise Unavailable("not inside a Git worktree")
    return Path(result.stdout.strip()).resolve()


def runtime(root: Path) -> Path:
    return root / ".graphify-local"


def executable(root: Path) -> Path:
    return (
        runtime(root)
        / "venv"
        / ("Scripts" if os.name == "nt" else "bin")
        / ("graphify.exe" if os.name == "nt" else "graphify")
    )


def python_executable(root: Path) -> Path:
    return executable(root).with_name("python.exe" if os.name == "nt" else "python")


def local_env(root: Path, graph_out: Path | None = None) -> dict[str, str]:
    keep = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    home = runtime(root) / "home"
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "APPDATA": str(home / "AppData"),
            "GRAPHIFY_BACKEND": "none",
            "GRAPHIFY_NO_AUTO_REFRESH": "1",
            "GRAPHIFY_QUERY_LOG_DISABLE": "1",
        }
    )
    if graph_out is not None:
        env["GRAPHIFY_OUT"] = str(graph_out)
    return env


def safe_path(root: Path, rel: str) -> Path | None:
    p = Path(rel)
    parts = tuple(part.lower() for part in p.parts)
    # `backend/backup` and `backend/runtime` are first-class source domains.
    # Their names are denied everywhere else; nested sensitive data remains
    # excluded inside those domains too.
    domain = parts[:2] if len(parts) >= 2 and parts[0] == "backend" else ()
    if p.is_absolute() or any(
        (
            part in DENIED
            and not (
                index == 1 and domain in {("backend", "backup"), ("backend", "runtime")}
            )
        )
        or part == ".sonar-secrets-cli-workdir"
        or part.startswith(".env")
        for index, part in enumerate(parts)
    ):
        return None
    if not (p.parts and (p.parts[0] in SOURCE_DIRS or rel in ROOT_FILES)) or (
        p.suffix.lower() not in EXTENSIONS and rel not in ROOT_FILES
    ):
        return None
    full = root / p
    try:
        # Reject symlinks in every path component, not only the leaf.
        cursor = root
        for part in p.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        # Windows junctions and other reparse points can escape without being
        # reported as ordinary symlinks. Reject reparse points on every parent.
        cursor = root
        for part in p.parts:
            cursor = cursor / part
            try:
                if getattr(os.lstat(cursor), "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                ):
                    return None
            except AttributeError:
                if cursor.is_symlink():
                    return None
            except OSError:
                if cursor.is_symlink():
                    return None
        resolved = full.resolve(strict=True)
        resolved.relative_to(root)
        return full if resolved.is_file() else None
    except OSError:
        return None
    except ValueError:
        return None


def corpus_paths(root: Path) -> list[tuple[str, Path]]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        capture_output=True,
        check=True,
    )
    found = {}
    for raw in result.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if raw and (path := safe_path(root, raw)):
            found[raw.replace("\\", "/")] = path
    return sorted(found.items())


def scan(paths: list[tuple[str, Path]], deadline: float | None = None) -> None:
    deadline = deadline or time.monotonic() + TIMEOUT
    if not paths:
        raise Unavailable("no approved source files to scan")
    scanner = shutil.which("sonar")
    if not scanner:
        raise Unavailable("Sonar secrets scanner unavailable; graph update refused")
    # One bounded argument list per batch avoids Windows' per-process startup
    # cost and command-line limit while retaining fail-closed scan behavior.
    batch_size = 35
    for start in range(0, len(paths), batch_size):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable("secret scan timed out; graph update refused")
        try:
            result = subprocess.run(
                [
                    scanner,
                    "analyze",
                    "secrets",
                    *[str(p) for _, p in paths[start : start + batch_size]],
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=remaining,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Unavailable("secret scan failed; graph update refused") from exc
        if result.returncode:
            raise Unavailable(
                "secret scan failed or reported a finding; graph update refused"
            )


@contextlib.contextmanager
def process_lock(path: Path, deadline: float | None = None):
    deadline = deadline or time.monotonic() + TIMEOUT
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        while True:
            if time.monotonic() >= deadline:
                raise Unavailable("graph update lock timed out")
            try:
                if os.name == "nt":
                    msvcrt = __import__("msvcrt")

                    handle.seek(0)
                    if os.fstat(handle.fileno()).st_size == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                msvcrt = __import__("msvcrt")

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def state(
    root: Path, deadline: float | None = None
) -> tuple[list[tuple[str, Path]], str, dict[str, str]]:
    deadline = deadline or time.monotonic() + TIMEOUT
    paths = corpus_paths(root)
    before = {rel: _signature(path) for rel, path in paths}
    scan(paths, deadline)
    rows, hashes = [], {}
    for rel, path in paths:
        before_sig = _signature(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if before_sig != _signature(path) or before_sig != before[rel]:
            raise Unavailable("source changed during scan; retry update")
        rows.append((rel, digest))
        hashes[rel] = digest
    branch = (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    ref = (
        subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
        )
        .stdout.decode("utf-8", "replace")
        .strip()
    )
    stamp = hashlib.sha256(
        json.dumps(
            [
                WRAPPER_SCHEMA,
                VERSION,
                branch,
                ref,
                sorted(SOURCE_DIRS),
                sorted(ROOT_FILES),
                sorted(DENIED),
                sorted(EXTENSIONS),
                ["update", "--no-cluster"],
                rows,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return paths, stamp, hashes


def _signature(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_ino, info.st_size, info.st_mtime_ns, getattr(info, "st_ctime_ns", 0)


def _corpus_signature(root: Path) -> list[tuple[str, tuple[int, int, int, int]]]:
    return [(rel, _signature(path)) for rel, path in corpus_paths(root)]


def _git_identity(root: Path) -> tuple[str, str]:
    head = (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    ref = (
        subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
        )
        .stdout.decode("utf-8", "replace")
        .strip()
    )
    return head, ref


def _config_signature() -> str:
    config = [
        WRAPPER_SCHEMA,
        VERSION,
        sorted(SOURCE_DIRS),
        sorted(ROOT_FILES),
        sorted(DENIED),
        sorted(EXTENSIONS),
        ["update", "--no-cluster"],
    ]
    return hashlib.sha256(
        json.dumps(config, separators=(",", ":")).encode()
    ).hexdigest()


def _metadata(root: Path) -> dict:
    """Cheap freshness hint; never reads source contents."""
    return {
        "files": [[rel, list(sig)] for rel, sig in _corpus_signature(root)],
        "git": list(_git_identity(root)),
        "config": _config_signature(),
    }


def _metadata_matches(root: Path, metadata: dict, source_signature: list) -> bool:
    return (
        metadata.get("files") == [[rel, list(sig)] for rel, sig in source_signature]
        and metadata.get("git") == list(_git_identity(root))
        and metadata.get("config") == _config_signature()
    )


def _metadata_current(root: Path, pointer: dict) -> bool:
    try:
        if (
            pointer.get("schema") != WRAPPER_SCHEMA
            or pointer.get("graphify_version") != VERSION
        ):
            return False
        generation = generation_dir(root, pointer)
        graph = generation / "graphify-out" / "graph.json"
        return (
            not pointer.get("stale")
            and graph.is_file()
            and hashlib.sha256(graph.read_bytes()).hexdigest()
            == pointer.get("graph_sha256")
            and pointer.get("metadata") == _metadata(root)
        )
    except OSError, subprocess.SubprocessError, Unavailable:
        return False


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except OSError:
        return {}
    except ValueError:
        return {}


def generation_dir(root: Path, pointer: dict) -> Path:
    name = pointer.get("generation")
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{32}", name):
        raise Unavailable("active graph generation pointer is invalid")
    return runtime(root) / "generations" / name


def verify_version(root: Path) -> bool:
    py = python_executable(root)
    exe = executable(root)
    if not py.is_file() or not exe.is_file():
        return False
    try:
        result = subprocess.run(
            [
                str(py),
                "-c",
                "import importlib.metadata as m; print(m.version('graphifyy'))",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
            env=local_env(root),
        )
        return result.returncode == 0 and result.stdout.strip() == VERSION
    except OSError:
        return False
    except subprocess.SubprocessError:
        return False


def update(root: Path) -> int:
    deadline = time.monotonic() + TIMEOUT
    base = runtime(root)
    temp: Path | None = None
    # Avoid a long source scan when an explicit per-worktree setup is needed.
    if not verify_version(root):
        print(
            f"Graphify local: unavailable (Graphify {VERSION} unavailable; run setup)"
        )
        return 2
    try:
        with process_lock(base / "update.lock", deadline):
            current = read_json(base / "current.json")
            if _metadata_current(root, current) and verify_version(root):
                print("Graphify local: current")
                return 0
            metadata = _metadata(root)
            paths, fingerprint, hashes = state(root, deadline)
            if not _metadata_matches(
                root, metadata, [(rel, _signature(path)) for rel, path in paths]
            ):
                raise Unavailable("source changed during scan; retry update")
            current = read_json(base / "current.json")
            try:
                active = generation_dir(root, current)
            except Unavailable:
                active = base / "missing"
            graph = active / "graphify-out" / "graph.json"
            graph_digest = (
                hashlib.sha256(graph.read_bytes()).hexdigest()
                if graph.is_file()
                else None
            )
            if (
                current.get("fingerprint") == fingerprint
                and current.get("schema") == WRAPPER_SCHEMA
                and current.get("graphify_version") == VERSION
                and graph_digest is not None
                and graph_digest == current.get("graph_sha256")
                and verify_version(root)
            ):
                # The fingerprint covers source bytes and Git identity. File
                # stats can still change while those inputs remain identical,
                # so publish the metadata from this successful scan as well.
                if not _metadata_matches(
                    root, metadata, [(rel, _signature(path)) for rel, path in paths]
                ):
                    raise Unavailable("source changed during scan; retry update")
                current.update(
                    metadata=metadata,
                    graph_sha256=graph_digest,
                    stale=False,
                    updated=int(time.time()),
                )
                pending = base / "current.json.tmp"
                pending.write_text(json.dumps(current), encoding="utf-8")
                os.replace(pending, base / "current.json")
                print("Graphify local: current")
                return 0
            gen_id = uuid.uuid4().hex
            temp = base / "generations" / (".building-" + gen_id)
            temp.mkdir(parents=True, exist_ok=True)
            # Keep one stable corpus and Graphify output so its incremental cache
            # survives updates; the graph generation itself remains atomic.
            inputs = base / "inputs" / "corpus"
            inputs.mkdir(parents=True, exist_ok=True)
            wanted = set()
            for rel, source in paths:
                wanted.add(rel)
                dest = inputs / rel
                if (
                    dest.is_file()
                    and hashlib.sha256(dest.read_bytes()).hexdigest() == hashes[rel]
                ):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != hashes[rel]:
                    raise Unavailable("source changed after scan; graph update refused")
                dest.write_bytes(data)
            for file in inputs.rglob("*"):
                if file.is_file() and file.relative_to(inputs).as_posix() not in wanted:
                    file.unlink()
            out = base / "cache"
            env = local_env(root, out)
            remaining = deadline - time.monotonic()
            command = [
                str(executable(root)),
                "update",
                str(inputs),
                "--no-cluster",
            ]
            result = subprocess.run(
                command,
                cwd=base,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=remaining,
                check=False,
            )
            graph_data = read_json(out / "graph.json")
            nodes, edges = (
                graph_data.get("nodes"),
                graph_data.get("edges", graph_data.get("links")),
            )
            if (
                result.returncode
                or not isinstance(nodes, list)
                or not nodes
                or not isinstance(edges, list)
            ):
                raise Unavailable("Graphify update failed or returned an invalid graph")
            for edge in edges:
                if not isinstance(edge, dict) or not (
                    ("source" in edge and "target" in edge)
                    or ("src" in edge and "dst" in edge)
                ):
                    raise Unavailable("Graphify graph edge schema is invalid")
            # Preserve Graphify's raw relationship endpoints; this wrapper
            # does not assert that the upstream graph is directed.
            # Verify metadata only after the successful pre-read scan. Hashing
            # the full source corpus again needlessly doubles the update cost.
            if not _metadata_matches(
                root, metadata, [(rel, _signature(path)) for rel, path in paths]
            ):
                raise Unavailable(
                    "source changed during extraction; prior generation retained"
                )
            (temp / "graphify-out").mkdir(parents=True, exist_ok=True)
            shutil.copy2(out / "graph.json", temp / "graphify-out" / "graph.json")
            final = base / "generations" / gen_id
            temp.rename(final)
            temp = None
            pointer = {
                "generation": gen_id,
                "fingerprint": fingerprint,
                "schema": WRAPPER_SCHEMA,
                "graphify_version": VERSION,
                "updated": int(time.time()),
                "stale": False,
                "metadata": metadata,
                "graph_sha256": hashlib.sha256(
                    (final / "graphify-out" / "graph.json").read_bytes()
                ).hexdigest(),
            }
            pending = base / "current.json.tmp"
            pending.write_text(json.dumps(pointer), encoding="utf-8")
            os.replace(pending, base / "current.json")
            # Retain only current and immediately previous generation.
            generations = sorted(
                (
                    p
                    for p in (base / "generations").iterdir()
                    if p.is_dir() and not p.name.startswith(".building-")
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            keep = {gen_id, current.get("generation")}
            for old in generations:
                if old.name not in keep:
                    shutil.rmtree(old, ignore_errors=True)
            # Stable cache is bounded to this single worktree corpus.
            print("Graphify local: current (updated)")
            return 0
    except (OSError, subprocess.SubprocessError, Unavailable) as exc:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        # Do not mutate current.json outside the updater lock. Freshness is
        # derived from the source fingerprint and graph pointer at read time.
        reason = str(exc) if isinstance(exc, Unavailable) else "Graphify process failed"
        print(f"Graphify local: unavailable/stale ({reason})")
        return 2


def active_graph(root: Path) -> tuple[Path, Path]:
    current = read_json(runtime(root) / "current.json")
    if (
        current.get("schema") != WRAPPER_SCHEMA
        or current.get("graphify_version") != VERSION
    ):
        raise Unavailable("no compatible local graph; run update")
    gen = generation_dir(root, current)
    graph = gen / "graphify-out" / "graph.json"
    if current.get("stale") or not graph.is_file():
        raise Unavailable("no fresh local graph; run update")
    if not _metadata_current(root, current):
        raise Unavailable("no fresh local graph; run update")
    return gen, graph


def helper(
    root: Path,
    command: str,
    graph: Path,
    output: Path | None = None,
    export_format: str | None = None,
) -> int:
    script = Path(__file__).with_name("graphify_views.py").resolve()
    if not script.is_file():
        raise Unavailable("local graph view helper unavailable")
    args = [str(python_executable(root)), str(script), command, str(graph)]
    if command == "export":
        if output is None:
            raise Unavailable("local graph export destination missing")
        args.extend([export_format or "json", str(output)])
    return subprocess.run(
        args,
        cwd=runtime(root),
        env=local_env(root, graph.parent),
        stdin=None if command == "mcp" else subprocess.DEVNULL,
        timeout=None if command == "mcp" else TIMEOUT,
        check=False,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    up = sub.add_parser("update")
    up.add_argument("--session-start", action="store_true")
    sub.add_parser("status")
    for name in ("query", "path", "explain"):
        p = sub.add_parser(name)
        p.add_argument("terms", nargs=argparse.REMAINDER)
    exp = sub.add_parser("export")
    exp.add_argument("format", choices=("json", "html", "wiki"))
    exp.add_argument("--output", required=True)
    sub.add_parser("mcp")
    args = parser.parse_args(argv)
    try:
        root = repo_root(Path(__file__).parent)
        if args.command == "setup":
            venv = runtime(root) / "venv"
            venv.mkdir(parents=True, exist_ok=True)
            py = python_executable(root)
            if not py.is_file():
                subprocess.run(
                    [sys.executable, "-m", "venv", str(venv)],
                    check=True,
                    timeout=120,
                    env=local_env(root),
                )
            if not verify_version(root):
                pip = venv / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
                subprocess.run(
                    [str(pip), "install", f"graphifyy[mcp]=={VERSION}"],
                    check=True,
                    timeout=600,
                    env=local_env(root),
                )
            if not verify_version(root):
                raise Unavailable("installed Graphify version mismatch")
            print(f"Graphify {VERSION} installed locally; run update")
            return 0
        if args.command == "update":
            return update(root)
        if args.command == "status":
            try:
                current = read_json(runtime(root) / "current.json")
                gen = generation_dir(root, current)
                fresh = verify_version(root) and _metadata_current(root, current)
            except Unavailable:
                fresh = False
            except OSError:
                fresh = False
            except subprocess.SubprocessError:
                fresh = False
            print("Graphify local: " + ("current" if fresh else "stale/unavailable"))
            return 0 if fresh else 2
        if not verify_version(root):
            raise Unavailable("pinned Graphify unavailable; run setup")
        gen, graph = active_graph(root)
        if args.command == "mcp":
            return helper(root, "mcp", graph)
        if args.command == "export":
            output = Path(args.output).resolve()
            export_root = (runtime(root) / "exports").resolve()
            output.relative_to(export_root)
            if output == export_root:
                raise Unavailable(
                    "export target must be a file below the export directory"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            return helper(root, "export", graph, output, args.format)
        allowed = {
            "query": set(),
            "path": {"--directed", "--undirected"},
            "explain": {"--all"},
        }[args.command]
        terms = []
        command = [str(executable(root)), args.command]
        for term in args.terms:
            if term.startswith("-") and term not in allowed:
                raise Unavailable("unsupported Graphify option")
            terms.append(term)
        positional = [term for term in terms if term not in allowed]
        if args.command == "path" and "--directed" in terms and "--undirected" in terms:
            raise Unavailable("choose either --directed or --undirected")
        if args.command == "path" and len(positional) != 2:
            raise Unavailable("path requires a source and target")
        if args.command == "explain" and len(positional) != 1:
            raise Unavailable("explain requires one symbol")
        if not terms:
            raise Unavailable("Graphify terms are required")
        command.extend(terms)
        command += ["--graph", str(graph)]
        return subprocess.run(
            command,
            cwd=gen,
            env=local_env(root, graph.parent),
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        ).returncode
    except (Unavailable, OSError, subprocess.SubprocessError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Unavailable) else "local operation failed"
        print(f"Graphify local unavailable: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
