"""Pure parsing and projection for Garmin's morning Body Battery readings."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

_GARMIN_SOURCE = "Garmin Connect"
_TIMESTAMP_FIELDS = (
    "sleepStartTimestampGMT",
    "sleepStartTimestamp",
    "startTimestampGMT",
)
_END_TIMESTAMP_FIELDS = (
    "sleepEndTimestampGMT",
    "sleepEndTimestamp",
    "endTimestampGMT",
)


def timestamp(value: Any) -> datetime | None:
    """Normalize Garmin epoch seconds/milliseconds and ISO timestamps to UTC."""
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        number = None
    if number is not None and math.isfinite(number):
        try:
            seconds = number / 1000 if number > 10_000_000_000 else number
            return datetime.fromtimestamp(seconds, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    ).astimezone(timezone.utc)


def _first_present(record: dict[str, Any], fields: tuple[str, ...]) -> Any:
    return next(
        (record[field] for field in fields if record.get(field) not in (None, "")), None
    )


def _sleep_interval(record: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start = timestamp(_first_present(record, _TIMESTAMP_FIELDS))
    end = timestamp(_first_present(record, _END_TIMESTAMP_FIELDS))
    return start, end


def sleep_bounds(payload: Any) -> tuple[datetime | None, datetime | None]:
    """Find the first valid interval, preferring Garmin's dailySleepDTO."""
    pending = [payload]
    visited = 0
    while pending and visited < 100:
        current = pending.pop(0)
        visited += 1
        if isinstance(current, dict):
            start, end = _sleep_interval(current)
            if start is not None and end is not None and start <= end:
                return start, end
            daily_sleep = current.get("dailySleepDTO")
            if isinstance(daily_sleep, dict):
                pending.insert(0, daily_sleep)
            pending.extend(
                value for value in current.values() if isinstance(value, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(current[:50])
    return None, None


def _number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _validated_body_battery_sample(sample: Any) -> dict[str, Any] | None:
    if not isinstance(sample, (list, tuple)) or len(sample) < 2:
        return None
    observed_at = timestamp(sample[0])
    level = _number(sample[1])
    if observed_at is None or level is None or not 0 <= float(level) <= 100:
        return None
    key = observed_at.isoformat()
    return {"observed_at": key, "value": round(float(level))}


def body_battery_samples(records: Any) -> list[dict[str, Any]]:
    """Return validated, UTC-normalized Body Battery samples in time order."""
    values = records if isinstance(records, list) else [records]
    samples: dict[str, dict[str, Any]] = {}
    for record in values:
        if not isinstance(record, dict):
            continue
        raw_samples = record.get("bodyBatteryValuesArray") or record.get(
            "body_battery_values_array"
        )
        if not isinstance(raw_samples, list):
            continue
        for sample in raw_samples:
            normalized = _validated_body_battery_sample(sample)
            if normalized is not None:
                samples[normalized["observed_at"]] = normalized
    return sorted(samples.values(), key=lambda sample: sample["observed_at"])


def morning_body_battery_record(
    checkin_date: date,
    sleep_payload: Any,
    body_battery_payload: Any,
    *,
    attempted_at: str,
) -> dict[str, Any]:
    """Derive the last pre-sleep and first post-sleep Body Battery readings."""
    sleep_start, sleep_end = sleep_bounds(sleep_payload)
    record: dict[str, Any] = {
        "sleep_date": checkin_date.isoformat(),
        "attempted_at": attempted_at,
        "status": "not_available_today",
        "before_sleep": None,
        "morning": None,
        "source": _GARMIN_SOURCE,
    }
    if sleep_start is None or sleep_end is None:
        return record
    record["sleep_start_at"] = sleep_start.isoformat()
    record["sleep_end_at"] = sleep_end.isoformat()
    attempted = timestamp(attempted_at)
    samples = body_battery_samples(body_battery_payload)
    before_lower_bound = sleep_start - timedelta(hours=4)
    before = [
        sample
        for sample in samples
        if before_lower_bound <= timestamp(sample["observed_at"]) <= sleep_start
    ]
    morning_end = min(attempted, sleep_end + timedelta(hours=1)) if attempted else None
    morning = (
        [
            sample
            for sample in samples
            if sleep_end <= timestamp(sample["observed_at"]) <= morning_end
        ]
        if morning_end is not None
        else []
    )
    if before:
        record["before_sleep"] = before[-1]
    if morning:
        record["morning"] = morning[0]
    if record["before_sleep"] is not None and record["morning"] is not None:
        record["status"] = "ready"
    return record


def cached_result(
    record: dict[str, Any] | None,
    checkin_date: date,
    *,
    now: datetime,
    max_attempts: int = 3,
    retry_seconds: int = 900,
) -> dict[str, Any] | None:
    """Return the existing cache/retry decision without reading the system clock."""
    if not record or record.get("sleep_date") != checkin_date.isoformat():
        return None
    sleep_date = checkin_date.isoformat()
    if record.get("status") == "ready":
        return {"status": "already_loaded", "sleep_date": sleep_date}
    try:
        attempts = int(record.get("attempts") or 1)
    except (TypeError, ValueError, OverflowError):
        attempts = 1
    if attempts >= max_attempts:
        return {"status": "attempts_exhausted", "sleep_date": sleep_date}
    attempted = timestamp(record.get("attempted_at"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    if attempted and (now - attempted).total_seconds() < retry_seconds:
        return {"status": "retry_wait", "sleep_date": sleep_date}
    return None
