"""Count warning and error log entries by event name; never print log text.

    python scripts/prod_logs.py --log-file <container log in the system temp directory> [--since ISO]
    python scripts/prod_logs.py --url <app address> --password-file <secret file> [--since ISO]

The first form reads container logs saved from the Unraid MCP; the second the
app's own redacted recent entries (`/api/logs`). Prints counts per level and
event name, the Garmin cleanup count and plan-sync error events. Exit 0 no
ERROR entry, 1 ERROR entries found, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any

from prod_client import ProdError, Session, scratch_path

EVENT = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
LEVEL = re.compile(r"\b(ERROR|WARNING|CRITICAL)\b")
CLEANUP = "garmin_past_workouts_removed"
LEVELS = ("CRITICAL", "ERROR", "WARNING")


def parse(line: str) -> dict[str, Any] | None:
    """A JSON log entry from a raw line, which may carry a Docker time prefix."""
    start = line.find("{")
    if start < 0:
        return None
    try:
        entry = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    return entry if isinstance(entry, dict) else None


def event_name(entry: dict[str, Any]) -> str:
    name = str(entry.get("event") or "log")
    return name if EVENT.match(name) else "unnamed"


def classify(
    raw: dict[str, Any] | str, since: str | None
) -> tuple[str, str, int] | None:
    """Level, event name and Garmin cleanup count of one entry, or None to skip it."""
    entry = parse(raw) if isinstance(raw, str) else raw
    if entry is None:
        match = LEVEL.search(raw) if isinstance(raw, str) else None
        return (match[1], "unparsed", 0) if match else None
    stamp = str(entry.get("timestamp") or "")
    if since and stamp and stamp < since:
        return None
    name = event_name(entry)
    count = (entry.get("context") or {}).get("count") if name == CLEANUP else 0
    level = str(entry.get("level") or "").upper()
    return level, name, count if isinstance(count, int) else 0


def summarize(entries: list[dict[str, Any] | str], since: str | None) -> dict[str, Any]:
    levels: Counter[str] = Counter()
    events: Counter[tuple[str, str]] = Counter()
    cleanup = 0
    for raw in entries:
        found = classify(raw, since)
        if found is None:
            continue
        level, name, count = found
        cleanup += count
        if level in LEVELS:
            levels[level] += 1
            events[(level, name)] += 1
    return {"levels": levels, "events": events, "garmin_removed": cleanup}


def report(summary: dict[str, Any]) -> list[str]:
    lines = [f"{level} {summary['levels'][level]}" for level in LEVELS]
    for (level, name), count in sorted(summary["events"].items()):
        lines.append(f"  {level} {name} {count}")
    lines.append(f"garmin past workouts removed: {summary['garmin_removed']}")
    plan = sum(
        count
        for (_level, name), count in summary["events"].items()
        if "plan" in name and ("error" in name or "fail" in name)
    )
    lines.append(f"plan sync error events: {plan}")
    return lines


def load(args: argparse.Namespace) -> list[dict[str, Any] | str]:
    if args.log_file:
        try:
            text = scratch_path(args.log_file).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            raise ProdError("cannot read the log file") from None
        return list(text.splitlines())
    session = Session(args.url, args.ca_file)
    session.login(args.password_file)
    try:
        data = session.get_json("/api/logs?limit=500")
    finally:
        session.logout()
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--log-file")
    source.add_argument("--url")
    parser.add_argument("--password-file")
    parser.add_argument("--since", help="ISO time; older entries are skipped")
    parser.add_argument("--ca-file")
    args = parser.parse_args(argv)
    if args.url and not args.password_file:
        parser.error("--url needs --password-file")
    try:
        summary = summarize(load(args), args.since)
    except ProdError as exc:
        print(f"FAIL {exc}")
        return 2
    for line in report(summary):
        print(line)
    return 1 if summary["levels"]["ERROR"] or summary["levels"]["CRITICAL"] else 0


if __name__ == "__main__":
    sys.exit(main())
