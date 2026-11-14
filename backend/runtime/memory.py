"""Content-free Linux process memory counters for operational diagnostics."""

import os
import time
from pathlib import Path

# The process start as the runtime sees it: this module loads at startup.
_STARTED = time.monotonic()

_STATUS_BYTES = {
    "VmRSS": "rss_bytes",
    "VmHWM": "peak_rss_bytes",
    "VmLck": "locked_bytes",
    "VmSize": "virtual_bytes",
    "RssAnon": "anonymous_rss_bytes",
    "RssFile": "file_rss_bytes",
}


def process_memory(proc_root: Path = Path("/proc")) -> dict[str, int]:
    """Return available counters only; never expose mapping addresses or paths."""
    counters: dict[str, int] = {}
    try:
        with (proc_root / "self/status").open(
            encoding="ascii", errors="replace"
        ) as source:
            for line in source:
                name, _, raw = line.partition(":")
                values = raw.split()
                if name in _STATUS_BYTES and len(values) == 2 and values[1] == "kB":
                    counters[_STATUS_BYTES[name]] = int(values[0]) * 1024
                elif name == "Threads" and len(values) == 1:
                    counters["threads"] = int(values[0])
    except OSError, ValueError, MemoryError:
        pass
    try:
        with (proc_root / "self/maps").open(
            encoding="ascii", errors="replace"
        ) as source:
            counters["mapping_count"] = sum(1 for _ in source)
    except OSError, MemoryError:
        pass
    try:
        counters["mapping_limit"] = int(
            (proc_root / "sys/vm/max_map_count").read_text(encoding="ascii").strip()
        )
    except OSError, ValueError, MemoryError:
        pass
    return counters


def process_settings() -> dict[str, int | None]:
    """Uptime in seconds and the allocator arena limit (the one env value shown)."""
    try:
        arenas: int | None = int(os.environ.get("MALLOC_ARENA_MAX", ""))
    except ValueError:
        arenas = None
    return {"uptime_s": int(time.monotonic() - _STARTED), "malloc_arena_max": arenas}
