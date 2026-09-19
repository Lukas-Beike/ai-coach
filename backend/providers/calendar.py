"""Pure, bounded iCalendar parsing and recurrence expansion."""
from __future__ import annotations

import calendar as calendar_module
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.errors import UNSUPPORTED_BYDAY_ERROR, AppError

MAX_EXTERNAL_CALENDAR_BYTES = 2_000_000
EXTERNAL_CALENDAR_WINDOW_DAYS = 120
ICAL_MAX_RECURRENCE_COUNT = 1000
ICAL_MAX_RECURRENCE_PERIODS = 8000
ICAL_NO_TRAINING_MARKER = "[NO_TRAINING]"
ICAL_NO_INTENSITY_MARKER = "[NO_INTENSITY]"
ICAL_SHORT_ONLY_MARKER = "[SHORT_ONLY]"
ICAL_TRAINING_MARKERS = (ICAL_NO_TRAINING_MARKER, ICAL_NO_INTENSITY_MARKER, ICAL_SHORT_ONLY_MARKER)
ICAL_DAY_NUMBERS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def parse_ics_value(value: str) -> str:
    return value.replace("\\N", "\n").replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def parse_ics_date(value: str) -> str | None:
    match = re.search(r"(\d{8})", value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}").isoformat()
    except ValueError:
        return None


def _decode_ical(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(400, "Der Kalender-Feed ist keine gültige UTF-8-iCalendar-Datei.") from exc


def _unfold_lines(text: str) -> list[str]:
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if len(line) > 20000:
            raise AppError(400, "Der Kalender-Feed enthält eine zu lange Zeile.")
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _validate_ical_structure(lines: list[str]) -> None:
    nonempty = [line for line in lines if line]
    if not nonempty or nonempty[0].upper() != "BEGIN:VCALENDAR" or nonempty[-1].upper() != "END:VCALENDAR":
        raise AppError(400, "Der Kalender-Feed muss ein vollständiges VCALENDAR-Dokument sein.")
    stack: list[str] = []
    for line in nonempty:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            stack.append(upper[6:])
        elif upper.startswith("END:"):
            if not stack or stack.pop() != upper[4:]:
                raise AppError(400, "Der Kalender-Feed enthält ungültige Komponenten.")
        elif ":" not in line:
            raise AppError(400, "Der Kalender-Feed enthält eine ungültige Eigenschaft.")
    if stack:
        raise AppError(400, "Der Kalender-Feed enthält nicht geschlossene Komponenten.")


def unfold_ical(payload: bytes, *, max_bytes: int = MAX_EXTERNAL_CALENDAR_BYTES, error: Any = None) -> list[str]:
    """Validate and unfold a feed; ``error`` is retained for old primitive callers."""
    try:
        if not isinstance(payload, (bytes, bytearray)) or len(payload) > max_bytes:
            raise AppError(413, "Der Kalender-Feed ist zu groß.")
        lines = _unfold_lines(_decode_ical(payload))
        _validate_ical_structure(lines)
        return lines
    except AppError as exc:
        if error is not None:
            raise error(exc.status, exc.message) from exc
        raise


def ical_duration(raw: str) -> timedelta | None:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", raw.strip().upper())
    if not match:
        return None
    days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
    duration = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return duration if duration.total_seconds() > 0 else None


def _ical_temporal_value(raw: str, parameters: dict[str, str], local_zone: tzinfo) -> tuple[datetime, bool] | None:
    value = raw.strip()
    is_date = parameters.get("VALUE", "").upper() == "DATE" or bool(re.fullmatch(r"\d{8}", value))
    try:
        if is_date:
            return datetime.combine(datetime.strptime(value[:8], "%Y%m%d").date(), datetime.min.time(), local_zone), True  # noqa: DTZ007
        if value.endswith("Z"):
            parsed = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.strptime(value, "%Y%m%dT%H%M" if len(value) == 13 else "%Y%m%dT%H%M%S")  # noqa: DTZ007
            name = parameters.get("TZID", "").strip('"')
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo(name)) if name else parsed.replace(tzinfo=local_zone)
            except (ZoneInfoNotFoundError, ValueError):
                parsed = parsed.replace(tzinfo=local_zone)
        return parsed.astimezone(local_zone), False
    except (TypeError, ValueError):
        return None


def _ical_description_contains(description: Any, marker: str) -> bool:
    return marker.casefold() in str(description or "").casefold()


def ical_training_impact(description: Any) -> bool:
    return any(_ical_description_contains(description, marker) for marker in ICAL_TRAINING_MARKERS)


def ical_training_relevant(description: Any) -> bool:
    text = str(description or "").strip()
    return bool(text) and not _ical_description_contains(text, ICAL_NO_TRAINING_MARKER)


def ical_no_intensity(description: Any) -> bool:
    return _ical_description_contains(description, ICAL_NO_INTENSITY_MARKER)


def ical_short_only(description: Any) -> bool:
    return _ical_description_contains(description, ICAL_SHORT_ONLY_MARKER)


def _ical_rule_values(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in raw.split(";"):
        key, separator, value = part.partition("=")
        key = key.strip().upper()
        if not separator or not key or key in values:
            raise AppError(400, "Die Kalender-Wiederholung ist ungültig oder doppelt angegeben.")
        values[key] = value.strip().upper()
    supported = {"FREQ", "COUNT", "UNTIL", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"}
    if set(values) - supported:
        raise AppError(400, "Diese Kalender-Wiederholungsregel wird nicht unterstützt.")
    return values


def _ical_rule_integer(values: dict[str, str], name: str, minimum: int, maximum: int, *, allow_negative: bool = False) -> list[int]:
    result: list[int] = []
    if not values.get(name):
        return result
    for raw_value in values[name].split(","):
        try:
            number = int(raw_value)
        except ValueError as exc:
            raise AppError(400, f"{name} der Kalender-Wiederholung muss aus ganzen Zahlen bestehen.") from exc
        if number == 0 or number < minimum or number > maximum or (number < 0 and not allow_negative):
            raise AppError(400, f"{name} der Kalender-Wiederholung ist ungültig.")
        if number in result:
            raise AppError(400, f"{name} der Kalender-Wiederholung ist doppelt angegeben.")
        result.append(number)
    return result


def _ical_rule_bydays(values: dict[str, str], frequency: str) -> list[tuple[int, int | None]]:
    result: list[tuple[int, int | None]] = []
    for token in values.get("BYDAY", "").split(",") if values.get("BYDAY") else []:
        match = re.fullmatch(r"([+-]?\d{1,2})?([A-Z]{2})", token)
        if not match or match.group(2) not in ICAL_DAY_NUMBERS:
            raise AppError(400, UNSUPPORTED_BYDAY_ERROR)
        ordinal = int(match.group(1)) if match.group(1) else None
        if ordinal == 0 or (ordinal is not None and abs(ordinal) > 53):
            raise AppError(400, UNSUPPORTED_BYDAY_ERROR)
        if frequency in {"DAILY", "WEEKLY"} and ordinal is not None:
            raise AppError(400, "Eine BYDAY-Position wird nur für MONTHLY oder YEARLY unterstützt.")
        item = (ICAL_DAY_NUMBERS[match.group(2)], ordinal)
        if item in result:
            raise AppError(400, UNSUPPORTED_BYDAY_ERROR)
        result.append(item)
    return result


def _ical_rrule(raw: str, local_zone: tzinfo) -> dict[str, Any]:
    values = _ical_rule_values(raw)
    frequency = values.get("FREQ")
    if frequency not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise AppError(400, "Diese Kalender-Wiederholungsfrequenz wird nicht unterstützt.")
    try:
        count = int(values["COUNT"]) if values.get("COUNT") else None
    except ValueError as exc:
        raise AppError(400, "COUNT der Kalender-Wiederholung muss eine ganze Zahl sein.") from exc
    if count is not None and not 1 <= count <= ICAL_MAX_RECURRENCE_COUNT:
        raise AppError(400, f"COUNT der Kalender-Wiederholung muss zwischen 1 und {ICAL_MAX_RECURRENCE_COUNT} liegen.")
    try:
        interval = int(values.get("INTERVAL", "1"))
    except ValueError as exc:
        raise AppError(400, "INTERVAL der Kalender-Wiederholung muss eine ganze Zahl sein.") from exc
    if not 1 <= interval <= ICAL_MAX_RECURRENCE_COUNT:
        raise AppError(400, "INTERVAL der Kalender-Wiederholung ist zu groß.")
    bydays = _ical_rule_bydays(values, frequency)
    bymonthday = _ical_rule_integer(values, "BYMONTHDAY", -31, 31, allow_negative=True)
    bymonth = _ical_rule_integer(values, "BYMONTH", 1, 12)
    bysetpos = _ical_rule_integer(values, "BYSETPOS", -366, 366, allow_negative=True)
    if bysetpos and frequency in {"DAILY", "WEEKLY"}:
        raise AppError(400, "BYSETPOS wird nur für MONTHLY oder YEARLY unterstützt.")
    wkst = ICAL_DAY_NUMBERS.get(values.get("WKST", "MO"))
    if wkst is None:
        raise AppError(400, "WKST der Kalender-Wiederholung ist ungültig.")
    until = None
    if values.get("UNTIL"):
        temporal = _ical_temporal_value(values["UNTIL"], {}, local_zone)
        if temporal is None:
            raise AppError(400, "UNTIL der Kalender-Wiederholung ist ungültig.")
        until = temporal[0]
    return {"frequency": frequency, "count": count, "interval": interval, "bydays": bydays, "bymonthday": bymonthday,
            "bymonth": bymonth, "bysetpos": bysetpos, "wkst": wkst, "until": until}


def _ical_shift_local(value: datetime, days: int) -> datetime:
    return datetime.combine(value.date() + timedelta(days=days), value.timetz().replace(tzinfo=None), value.tzinfo)


def _ical_matches_byday(value: date, bydays: list[tuple[int, int | None]]) -> bool:
    for weekday, ordinal in bydays:
        if value.weekday() != weekday:
            continue
        if ordinal is None or (ordinal > 0 and (value.day - 1) // 7 + 1 == ordinal):
            return True
        if ordinal < 0 and -((calendar_module.monthrange(value.year, value.month)[1] - value.day) // 7 + 1) == ordinal:
            return True
    return False


def _ical_matches_date_filters(value: date, rule: dict[str, Any]) -> bool:
    if rule["bymonth"] and value.month not in rule["bymonth"]:
        return False
    if rule["bymonthday"]:
        last = calendar_module.monthrange(value.year, value.month)[1]
        if value.day not in {n if n > 0 else last + n + 1 for n in rule["bymonthday"]}:
            return False
    return not rule["bydays"] or _ical_matches_byday(value, rule["bydays"])


def _ical_period_dates(base: date, year: int, month: int, rule: dict[str, Any]) -> list[date]:
    if rule["bymonth"] and month not in rule["bymonth"]:
        return []
    last = calendar_module.monthrange(year, month)[1]
    if rule["bymonthday"]:
        days = sorted({n if n > 0 else last + n + 1 for n in rule["bymonthday"]})
        candidates = [date(year, month, day) for day in days if 1 <= day <= last]
    elif rule["bydays"]:
        candidates = [date(year, month, day) for day in range(1, last + 1)]
    else:
        candidates = [date(year, month, base.day)] if base.day <= last else []
    return [item for item in candidates if _ical_matches_date_filters(item, rule)]


def _ical_apply_bysetpos(candidates: list[date], rule: dict[str, Any]) -> list[date]:
    ordered = sorted(set(candidates))
    if not rule["bysetpos"]:
        return ordered
    selected = set()
    for position in rule["bysetpos"]:
        index = position - 1 if position > 0 else len(ordered) + position
        if 0 <= index < len(ordered):
            selected.add(ordered[index])
    return sorted(selected)


def _ical_add_start(starts: list[datetime], value: datetime, first: date, last: date) -> None:
    if first <= value.date() <= last and value not in starts:
        starts.append(value)


def _ical_daily(base: datetime, rule: dict[str, Any], first: date, last: date) -> list[datetime]:
    starts: list[datetime] = []
    index = 0 if rule["count"] is not None else max(0, math.ceil((first - base.date()).days / rule["interval"]) - 1)
    occurrences = 0
    while index <= (index + ICAL_MAX_RECURRENCE_COUNT * 366):
        value = _ical_shift_local(base, index * rule["interval"])
        if value.date() > last or (rule["until"] is not None and value > rule["until"]):
            break
        if _ical_matches_date_filters(value.date(), rule):
            if rule["count"] is not None and occurrences >= rule["count"]:
                break
            occurrences += 1
            _ical_add_start(starts, value, first, last)
        index += 1
    return starts


def _ical_weekly(base: datetime, rule: dict[str, Any], first: date, last: date) -> list[datetime]:
    base_date = base.date()
    base_week = base_date - timedelta(days=(base_date.weekday() - rule["wkst"]) % 7)
    target = first - timedelta(days=(first.weekday() - rule["wkst"]) % 7)
    slot = 0 if rule["count"] is not None else max(0, max(0, (target - base_week).days // 7) // rule["interval"] - 1)
    bydays = rule["bydays"] or [(base_date.weekday(), None)]
    starts: list[datetime] = []
    occurrences = 0
    while slot <= slot + ICAL_MAX_RECURRENCE_PERIODS:
        week = base_week + timedelta(days=slot * rule["interval"] * 7)
        if week > last:
            break
        for weekday, _ordinal in sorted(bydays):
            day = week + timedelta(days=(weekday - rule["wkst"]) % 7)
            if day < base_date or not _ical_matches_date_filters(day, {**rule, "bydays": []}):
                continue
            value = _ical_shift_local(base, (day - base_date).days)
            if rule["count"] is not None and occurrences >= rule["count"]:
                return starts
            if rule["until"] is not None and value > rule["until"]:
                return starts
            occurrences += 1
            _ical_add_start(starts, value, first, last)
        slot += 1
    return starts


def _ical_period(base: datetime, rule: dict[str, Any], first: date, last: date) -> list[datetime]:
    base_date = base.date()
    monthly = rule["frequency"] == "MONTHLY"
    base_period = base_date.year * 12 + base_date.month - 1 if monthly else base_date.year
    target_period = first.year * 12 + first.month - 1 if monthly else first.year
    period = 0 if rule["count"] is not None else max(0, max(0, target_period - base_period) // rule["interval"] - 1)
    starts: list[datetime] = []
    occurrences = 0
    while period <= period + ICAL_MAX_RECURRENCE_PERIODS:
        if monthly:
            month_index = base_date.year * 12 + base_date.month - 1 + period * rule["interval"]
            year, month = divmod(month_index, 12)
            months = [month + 1]
        else:
            year = base_date.year + period * rule["interval"]
            months = rule["bymonth"] or (range(1, 13) if rule["bydays"] or rule["bymonthday"] else [base_date.month])
            months = list(months)
        candidates = [d for month in months for d in _ical_period_dates(base_date, year, month, rule)]
        for candidate in [d for d in _ical_apply_bysetpos(candidates, rule) if d >= base_date]:
            value = _ical_shift_local(base, (candidate - base_date).days)
            if rule["until"] is not None and value > rule["until"]:
                return starts
            if rule["count"] is not None and occurrences >= rule["count"]:
                return starts
            occurrences += 1
            _ical_add_start(starts, value, first, last)
        marker = date(year, months[-1], 1) if monthly else date(year, 1, 1)
        if marker > last:
            break
        period += 1
    return starts


def _ical_recurrence_starts(event: dict[str, Any], rule: dict[str, Any], first: date, last: date) -> list[datetime]:
    if rule["frequency"] == "DAILY":
        return _ical_daily(event["start"], rule, first, last)
    if rule["frequency"] == "WEEKLY":
        return _ical_weekly(event["start"], rule, first, last)
    return _ical_period(event["start"], rule, first, last)


def _ical_duration(event: dict[str, Any]) -> timedelta:
    start = event["start"]
    end = event.get("end")
    if end is None:
        end = start + event.get("duration", timedelta(days=1) if event.get("all_day") else timedelta(hours=1))
    if end <= start:
        end = start + (timedelta(days=1) if event.get("all_day") else timedelta(minutes=30))
    return end - start


def _ical_overlaps(start: datetime, duration: timedelta, first: date, last: date) -> bool:
    return start.date() <= last and (start + duration - timedelta(microseconds=1)).date() >= first


def _ical_instances(event: dict[str, Any], first: date, last: date, local_zone: tzinfo, excluded: set[datetime] | None = None) -> list[dict[str, Any]]:
    duration = _ical_duration(event)
    if event.get("rrules"):
        if event.get("unsupported_recurrence"):
            raise AppError(400, "Diese Kalender-Wiederholung wird nicht unterstützt.")
        starts: list[datetime] = []
        recurrence_first = first - timedelta(days=duration.days + 1)
        for raw in event["rrules"]:
            starts.extend(_ical_recurrence_starts(event, _ical_rrule(raw, local_zone), recurrence_first, last))
        starts = sorted(set(starts))
    else:
        starts = [event["start"]] if _ical_overlaps(event["start"], duration, first, last) else []
    starts.extend(value for value in event.get("rdates", []) if value not in starts and _ical_overlaps(value, duration, first, last))
    excluded_values = set(event.get("exdates", [])) | set(excluded or ())
    records = []
    for start in starts:
        if start in excluded_values or not _ical_overlaps(start, duration, first, last):
            continue
        end = start + duration
        records.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ical-calendar:{event['uid']}:{start.isoformat()}")), "uid": event["uid"],
            "name": event.get("name") or "Privater Kalendereintrag", "event_date": start.date().isoformat(), "start_local": start.isoformat(),
            "end_local": end.isoformat(), "duration_minutes": max(1, round(duration.total_seconds() / 60)), "all_day": bool(event.get("all_day")),
            "training_impact": ical_training_impact(event.get("description")), "training_relevant": ical_training_relevant(event.get("description")),
            "no_intensity": ical_no_intensity(event.get("description")), "short_only": ical_short_only(event.get("description"))})
    return records


def _ical_property_parameters(key_part: str) -> tuple[str, dict[str, str]]:
    parts = key_part.split(";")
    parameters = {name.upper(): value for parameter in parts[1:] for name, separator, value in [parameter.partition("=")] if separator}
    return parts[0].upper(), parameters


def _ical_store_property(event: dict[str, Any], key: str, raw: str, parameters: dict[str, str], local_zone: tzinfo) -> None:
    if key in {"DTSTART", "DTEND"}:
        value = _ical_temporal_value(raw, parameters, local_zone)
        if value:
            event["all_day"] = value[1] if key == "DTSTART" else event.get("all_day", value[1])
            event["start" if key == "DTSTART" else "end"] = value[0]
        return
    if key in {"EXDATE", "RDATE"}:
        if key == "RDATE" and "/" in raw:
            raise AppError(400, "RDATE mit Zeiträumen wird nicht unterstützt.")
        field = "exdates" if key == "EXDATE" else "rdates"
        message = "EXDATE der Kalender-Wiederholung ist ungültig." if key == "EXDATE" else "RDATE der Kalender-Wiederholung ist ungültig."
        for value in raw.split(","):
            parsed = _ical_temporal_value(value, parameters, local_zone)
            if parsed is None:
                raise AppError(400, message)
            event.setdefault(field, []).append(parsed[0])
        return
    fields = {"UID": ("uid", 500), "SUMMARY": ("name", 200), "DESCRIPTION": ("description", 2000), "STATUS": ("status", 30)}
    if key in fields:
        field, limit = fields[key]
        event[field] = parse_ics_value(raw)[:limit]
    elif key == "DURATION":
        duration = ical_duration(raw)
        if duration:
            event["duration"] = duration
    elif key == "RRULE":
        event.setdefault("rrules", []).append(raw)
    elif key == "RECURRENCE-ID":
        parsed = _ical_temporal_value(raw, parameters, local_zone)
        if parsed is None:
            raise AppError(400, "RECURRENCE-ID der Kalender-Wiederholung ist ungültig.")
        event["recurrence_id"] = parsed[0]
    elif key == "EXRULE":
        event["unsupported_recurrence"] = True


def _ical_parsed_events(payload: bytes, local_zone: tzinfo) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    nested = 0
    for line in unfold_ical(payload):
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if current is not None and upper.startswith("BEGIN:"):
            nested += 1
            continue
        if nested:
            if upper.startswith("END:"):
                nested -= 1
            continue
        if upper == "END:VEVENT":
            if current and current.get("status", "").upper() != "CANCELLED" and not (current.get("uid") and current.get("start")):
                raise AppError(400, "Ein Kalendertermin benötigt UID und DTSTART.")
            if current and current.get("uid") and (current.get("start") or (current.get("status", "").upper() == "CANCELLED" and current.get("recurrence_id") is not None)):
                events.append(current)
            current = None
            continue
        if current is not None and ":" in line:
            key_part, raw = line.split(":", 1)
            key, parameters = _ical_property_parameters(key_part)
            _ical_store_property(current, key, raw, parameters, local_zone)
    return events


def _ical_window(window_start: date | None, window_end: date | None, today: date) -> tuple[date, date]:
    first = window_start or today
    last = window_end or first + timedelta(days=EXTERNAL_CALENDAR_WINDOW_DAYS)
    if last < first or (last - first).days > EXTERNAL_CALENDAR_WINDOW_DAYS:
        raise AppError(400, "Das Kalenderfenster ist ungültig oder zu groß.")
    return first, last


def parse_ical_calendar(payload: bytes, *, local_zone: tzinfo, today: date, window_start: date | None = None, window_end: date | None = None) -> list[dict[str, Any]]:
    first, last = _ical_window(window_start, window_end, today)
    events = _ical_parsed_events(payload, local_zone)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        if event.get("recurrence_id") is not None or event.get("status", "").upper() == "CANCELLED":
            continue
        exceptions = {item["recurrence_id"] for item in events if item.get("uid") == event.get("uid") and item.get("recurrence_id") is not None}
        for item in _ical_instances(event, first, last, local_zone, exceptions):
            key = (item["uid"], item["start_local"])
            if key not in result and len(result) >= ICAL_MAX_RECURRENCE_COUNT:
                raise AppError(400, f"Der Kalender-Feed enthält mehr als {ICAL_MAX_RECURRENCE_COUNT} Termine im Syncfenster.")
            result.setdefault(key, item)
    for event in events:
        if event.get("recurrence_id") is None or event.get("status", "").upper() == "CANCELLED":
            continue
        for item in _ical_instances(event, first, last, local_zone):
            key = (item["uid"], item["start_local"])
            if key not in result and len(result) >= ICAL_MAX_RECURRENCE_COUNT:
                raise AppError(400, f"Der Kalender-Feed enthält mehr als {ICAL_MAX_RECURRENCE_COUNT} Termine im Syncfenster.")
            result.setdefault(key, item)
    return sorted(result.values(), key=lambda item: (item["start_local"], item["name"], item["uid"]))[:ICAL_MAX_RECURRENCE_COUNT]
