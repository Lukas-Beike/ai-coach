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
SOURCE_CHANGED = "source changed during scan; retry update"
GRAPH_FILE = Path("graphify-out") / "graph.json"
CURRENT_FILE = "current.json"


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


def _denied_path(p: Path, rel: str) -> bool:
    parts = tuple(part.lower() for part in p.parts)
    # `backend/backup` and `backend/runtime` are first-class source domains.
    # Their names are denied everywhere else; nested sensitive data remains
    # excluded inside those domains too.
    domain = parts[:2] if len(parts) >= 2 and parts[0] == "backend" else ()
    return p.is_absolute() or any(
        (
            part in DENIED
            and not (
                index == 1 and domain in {("backend", "backup"), ("backend", "runtime")}
            )
        )
        or part == ".sonar-secrets-cli-workdir"
        or part.startswith(".env")
        for index, part in enumerate(parts)
    )


def _approved_source_path(p: Path, rel: str) -> bool:
    if not p.parts or (p.parts[0] not in SOURCE_DIRS and rel not in ROOT_FILES):
        return False
    return p.suffix.lower() in EXTENSIONS or rel in ROOT_FILES


def _has_reparse_component(root: Path, parts: tuple[str, ...]) -> bool:
    cursor = root
    for part in parts:
        cursor = cursor / part
        try:
            attributes = getattr(os.lstat(cursor), "st_file_attributes", 0)
            if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                return True
        except AttributeError, OSError:
            if cursor.is_symlink():
                return True
    return False


def _contained_file(root: Path, path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return resolved.is_file()
    except OSError, ValueError:
        return False


def safe_path(root: Path, rel: str) -> Path | None:
    p = Path(rel)
    if _denied_path(p, rel) or not _approved_source_path(p, rel):
        return None
    full = root / p
    try:
        cursor = root
        for part in p.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        if _has_reparse_component(root, p.parts) or not _contained_file(root, full):
            return None
        return full
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
            raise Unavailable(SOURCE_CHANGED)
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
        graph = generation / GRAPH_FILE
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


def _source_metadata(root: Path, paths: list[tuple[str, Path]], metadata: dict) -> None:
    signatures = [(rel, _signature(path)) for rel, path in paths]
    if not _metadata_matches(root, metadata, signatures):
        raise Unavailable(SOURCE_CHANGED)


def _refresh_current(base: Path, current: dict, metadata: dict, digest: str) -> None:
    current.update(
        metadata=metadata, graph_sha256=digest, stale=False, updated=int(time.time())
    )
    pending = base / (CURRENT_FILE + ".tmp")
    pending.write_text(json.dumps(current), encoding="utf-8")
    os.replace(pending, base / CURRENT_FILE)


def _matching_graph(
    root: Path,
    base: Path,
    current: dict,
    fingerprint: str,
    metadata: dict,
    paths: list[tuple[str, Path]],
) -> bool:
    try:
        graph = generation_dir(root, current) / GRAPH_FILE
    except Unavailable:
        return False
    digest = hashlib.sha256(graph.read_bytes()).hexdigest() if graph.is_file() else None
    matches = (
        current.get("fingerprint") == fingerprint
        and current.get("schema") == WRAPPER_SCHEMA
        and current.get("graphify_version") == VERSION
        and digest is not None
        and digest == current.get("graph_sha256")
        and verify_version(root)
    )
    if not matches:
        return False
    assert digest is not None
    _source_metadata(root, paths, metadata)
    _refresh_current(base, current, metadata, digest)
    return True


def _copy_inputs(
    base: Path, paths: list[tuple[str, Path]], hashes: dict[str, str]
) -> Path:
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
    return inputs


def _run_graphify(root: Path, base: Path, inputs: Path, deadline: float) -> Path:
    out = base / "cache"
    command = [str(executable(root)), "update", str(inputs), "--no-cluster"]
    result = subprocess.run(
        command,
        cwd=base,
        env=local_env(root, out),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=deadline - time.monotonic(),
        check=False,
    )
    graph = out / "graph.json"
    graph_data = read_json(graph)
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
    if any(
        not isinstance(edge, dict)
        or not (
            ("source" in edge and "target" in edge) or ("src" in edge and "dst" in edge)
        )
        for edge in edges
    ):
        raise Unavailable("Graphify graph edge schema is invalid")
    return graph


def _publish_graph(
    base: Path,
    temp: Path,
    current: dict,
    fingerprint: str,
    metadata: dict,
    source: Path,
) -> None:
    (temp / GRAPH_FILE.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, temp / GRAPH_FILE)
    gen_id = temp.name.removeprefix(".building-")
    final = base / "generations" / gen_id
    temp.rename(final)
    pointer = {
        "generation": gen_id,
        "fingerprint": fingerprint,
        "schema": WRAPPER_SCHEMA,
        "graphify_version": VERSION,
        "updated": int(time.time()),
        "stale": False,
        "metadata": metadata,
        "graph_sha256": hashlib.sha256((final / GRAPH_FILE).read_bytes()).hexdigest(),
    }
    pending = base / (CURRENT_FILE + ".tmp")
    pending.write_text(json.dumps(pointer), encoding="utf-8")
    os.replace(pending, base / CURRENT_FILE)
    _prune_generations(base, gen_id, current.get("generation"))


def _prune_generations(base: Path, current_id: str, previous_id: str | None) -> None:
    generations = sorted(
        (
            p
            for p in (base / "generations").iterdir()
            if p.is_dir() and not p.name.startswith(".building-")
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    keep = {current_id, previous_id}
    for old in generations:
        if old.name not in keep:
            shutil.rmtree(old, ignore_errors=True)


def _update_locked(root: Path, base: Path, deadline: float) -> None:
    current = read_json(base / CURRENT_FILE)
    if _metadata_current(root, current) and verify_version(root):
        print("Graphify local: current")
        return
    metadata = _metadata(root)
    paths, fingerprint, hashes = state(root, deadline)
    _source_metadata(root, paths, metadata)
    current = read_json(base / CURRENT_FILE)
    if _matching_graph(root, base, current, fingerprint, metadata, paths):
        print("Graphify local: current")
        return
    gen_id = uuid.uuid4().hex
    temp = base / "generations" / (".building-" + gen_id)
    temp.mkdir(parents=True, exist_ok=True)
    try:
        graph = _run_graphify(root, base, _copy_inputs(base, paths, hashes), deadline)
        _source_metadata(root, paths, metadata)
        _publish_graph(base, temp, current, fingerprint, metadata, graph)
    except OSError, subprocess.SubprocessError, Unavailable:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
    print("Graphify local: current (updated)")


def update(root: Path) -> int:
    deadline = time.monotonic() + TIMEOUT
    base = runtime(root)
    # Avoid a long source scan when an explicit per-worktree setup is needed.
    if not verify_version(root):
        print(
            f"Graphify local: unavailable (Graphify {VERSION} unavailable; run setup)"
        )
        return 2
    try:
        with process_lock(base / "update.lock", deadline):
            _update_locked(root, base, deadline)
            return 0
    except (OSError, subprocess.SubprocessError, Unavailable) as exc:
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


def _setup(root: Path) -> int:
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


def _status(root: Path) -> int:
    try:
        current = read_json(runtime(root) / CURRENT_FILE)
        generation_dir(root, current)
        fresh = verify_version(root) and _metadata_current(root, current)
    except Unavailable, OSError, subprocess.SubprocessError:
        fresh = False
    print("Graphify local: " + ("current" if fresh else "stale/unavailable"))
    return 0 if fresh else 2


def _graph_command(
    root: Path, args: argparse.Namespace, generation: Path, graph: Path
) -> int:
    if args.command in {"mcp", "export"}:
        return _export_or_mcp(root, args, graph)
    allowed = {
        "query": set(),
        "path": {"--directed", "--undirected"},
        "explain": {"--all"},
    }[args.command]
    terms = args.terms
    if any(term.startswith("-") and term not in allowed for term in terms):
        raise Unavailable("unsupported Graphify option")
    positional = [term for term in terms if term not in allowed]
    if args.command == "path" and "--directed" in terms and "--undirected" in terms:
        raise Unavailable("choose either --directed or --undirected")
    if args.command == "path" and len(positional) != 2:
        raise Unavailable("path requires a source and target")
    if args.command == "explain" and len(positional) != 1:
        raise Unavailable("explain requires one symbol")
    if not terms:
        raise Unavailable("Graphify terms are required")
    command = [str(executable(root)), args.command, *terms, "--graph", str(graph)]
    return subprocess.run(
        command,
        cwd=generation,
        env=local_env(root, graph.parent),
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=False,
    ).returncode


def _export_or_mcp(root: Path, args: argparse.Namespace, graph: Path) -> int:
    if args.command == "mcp":
        return helper(root, "mcp", graph)
    output = Path(args.output).resolve()
    export_root = (runtime(root) / "exports").resolve()
    output.relative_to(export_root)
    if output == export_root:
        raise Unavailable("export target must be a file below the export directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    return helper(root, "export", graph, output, args.format)


def _dispatch(root: Path, args: argparse.Namespace) -> int:
    if args.command == "setup":
        return _setup(root)
    if args.command == "update":
        return update(root)
    if args.command == "status":
        return _status(root)
    if not verify_version(root):
        raise Unavailable("pinned Graphify unavailable; run setup")
    generation, graph = active_graph(root)
    return _graph_command(root, args, generation, graph)


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
        return _dispatch(root, args)
    except (Unavailable, OSError, subprocess.SubprocessError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Unavailable) else "local operation failed"
        print(f"Graphify local unavailable: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
