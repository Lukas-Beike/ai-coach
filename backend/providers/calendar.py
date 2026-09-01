"""Dependency-light iCalendar parsing primitives.

The HTTP client, application limits, timezone policy, and domain mapping stay
at the server boundary. These helpers only validate and normalize feed text.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import re


ErrorFactory = Callable[[int, str], Exception]


def parse_ics_value(value: str) -> str:
    return (
        value.replace("\\N", "\n").replace("\\n", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
        .strip()
    )


def parse_ics_date(value: str) -> str | None:
    raw = value.strip()
    match = re.search(r"(\d{8})", raw)
    if not match:
        return None
    try:
        return date.fromisoformat(f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}").isoformat()
    except ValueError:
        return None


def unfold_ical(payload: bytes, *, max_bytes: int, error: ErrorFactory) -> list[str]:
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > max_bytes:
        raise error(413, "Der Kalender-Feed ist zu groß.")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise error(400, "Der Kalender-Feed ist keine gültige UTF-8-iCalendar-Datei.") from exc
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if len(line) > 20000:
            raise error(400, "Der Kalender-Feed enthält eine zu lange Zeile.")
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    nonempty = [line for line in unfolded if line]
    if not nonempty or nonempty[0].upper() != "BEGIN:VCALENDAR" or nonempty[-1].upper() != "END:VCALENDAR":
        raise error(400, "Der Kalender-Feed muss ein vollständiges VCALENDAR-Dokument sein.")
    stack: list[str] = []
    for line in nonempty:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            stack.append(upper[6:])
            continue
        if upper.startswith("END:"):
            component = upper[4:]
            if not stack or stack.pop() != component:
                raise error(400, "Der Kalender-Feed enthält ungültige Komponenten.")
            continue
        if ":" not in line:
            raise error(400, "Der Kalender-Feed enthält eine ungültige Eigenschaft.")
    if stack:
        raise error(400, "Der Kalender-Feed enthält nicht geschlossene Komponenten.")
    return unfolded


def ical_duration(raw: str) -> timedelta | None:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", raw.strip().upper())
    if not match:
        return None
    days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
    duration = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return duration if duration.total_seconds() > 0 else None
