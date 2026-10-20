"""Map FIT activity files to canonical detail sets (origin FETCH).

The input is the raw bytes of one FIT activity file, decoded by ``fit_file``.
Field numbers follow the FIT SDK profile: record messages (20) provide streams
and lap messages (19) provide device laps. Values are converted to the canonical
units: metres, metres per second, beats or revolutions per minute, watts,
degrees Celsius and seconds.

Streams (``StreamResolution.FULL``) use these record fields: timestamp (253,
time zero is the first usable one), distance (5, /100 m), speed (enhanced 73,
else base 6, /1000 m/s), altitude (enhanced 78, else base 2, /5 - 500 m), heart
rate (3), cadence (4, plus the fractional cadence 53 /128 when present), power (7)
and temperature (13). The enhanced field is used per record when it holds a
usable value; an invalid sentinel falls back to the base field.

Device laps (``LapSource.DEVICE_LAPS``) use these lap fields: start_time (2),
total_elapsed_time (7, /1000 s), total_timer_time (8, /1000 s, moving duration),
total_distance (9, /100 m), average speed (enhanced 110, else base 13, /1000
m/s), average and maximum heart rate (15, 16), average cadence (17), average and
maximum power (19, 20), total ascent (21), normalized power (33) and intensity
(23: 0 active, 1 rest and 4 recovery, 2 warmup, 3 cooldown, 5 interval as
``WORK``; other values map to ``LAP``).

Not mapped: positions (0, 1), session and activity messages, developer fields,
device information, and lap run cadence.

The mapper is pure: it performs no I/O, logs nothing and never raises for
malformed bytes. Issues name the activity, the FIT field and a reason only.
Caller arguments are checked and may raise, as in the Garmin mapper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Final

from backend.canonical.activity_detail import (
    MAX_LAPS,
    MAX_STREAM_POINTS,
    MAX_STREAM_SPAN_S,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    clean_series,
)
from backend.canonical.mapping import IssueReason, MappingIssue, MappingResult
from backend.canonical.records import Provenance
from backend.canonical.validation import require_instance, require_text
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    StreamChannel,
    StreamResolution,
)
from backend.providers.fit_file import FitMessage, fit_field, fit_messages

# Version 1: first mapping of FIT activity detail sets (streams and device laps).
MAPPER_VERSION: Final = 1

# Same limit as the Garmin and Intervals mappers, so issues stay bounded.
MAX_FIT_ACTIVITY_ID_LENGTH: Final = 200

_RECORD_MESSAGE: Final = 20
_LAP_MESSAGE: Final = 19
_TIMESTAMP_FIELD: Final = 253
_CADENCE_FIELD: Final = 4
_FRACTIONAL_CADENCE_FIELD: Final = 53
_LAP_START_FIELD: Final = 2
_LAP_ELAPSED_FIELD: Final = 7
_LAP_INTENSITY_FIELD: Final = 23
# Record field per channel; speed and altitude prefer their enhanced fields.
_RECORD_CHANNEL_FIELDS: Final[tuple[tuple[StreamChannel, int], ...]] = (
    (StreamChannel.DISTANCE_M, 5),
    (StreamChannel.SPEED_MPS, 6),
    (StreamChannel.ALTITUDE_M, 2),
    (StreamChannel.HEART_RATE_BPM, 3),
    (StreamChannel.POWER_W, 7),
    (StreamChannel.TEMPERATURE_C, 13),
)
# Lap metric -> lap field number. Scaling and enhanced preference are in fit_file.
_LAP_METRIC_FIELDS: Final[tuple[tuple[str, int], ...]] = (
    ("moving_duration_s", 8),
    ("distance_m", 9),
    ("avg_speed_mps", 13),
    ("avg_hr", 15),
    ("max_hr", 16),
    ("avg_cadence", 17),
    ("avg_power", 19),
    ("max_power", 20),
    ("elevation_gain_m", 21),
    ("normalized_power", 33),
)
_LAP_KINDS: Final[Mapping[int, LapKind]] = {
    0: LapKind.LAP,
    1: LapKind.RECOVERY,
    2: LapKind.WARMUP,
    3: LapKind.COOLDOWN,
    4: LapKind.RECOVERY,
    5: LapKind.WORK,
}


def map_fit_activity_detail(
    data: object,
    *,
    provider_activity_id: str,
    provenance: Provenance,
) -> MappingResult[ActivityDetailSet]:
    """Map one FIT activity file into stream and lap sets (origin FETCH)."""
    ref = require_text(
        provider_activity_id,
        "provider_activity_id",
        max_length=MAX_FIT_ACTIVITY_ID_LENGTH,
    )
    require_instance(provenance, Provenance, "provenance")
    if provenance.provider is None:
        raise ValueError("provenance.provider is required for activity details")
    invalid = MappingIssue(ref, "fit", IssueReason.INVALID_TYPE)
    if not isinstance(data, bytes):
        return MappingResult(issues=(invalid,))
    try:
        messages = fit_messages(data)
    except ValueError:
        return MappingResult(issues=(invalid,))
    issues: list[MappingIssue] = []
    records: list[ActivityDetailSet] = []
    stream_set = _stream_set(ref, provenance, messages, issues)
    if stream_set is not None:
        records.append(stream_set)
    lap_set = _lap_set(ref, provenance, messages, issues)
    if lap_set is not None:
        records.append(lap_set)
    return MappingResult(records=tuple(records), issues=tuple(issues))


def _add_issue(
    issues: list[MappingIssue], ref: str, field: str, reason: IssueReason
) -> None:
    """Append one issue; identical (field, reason) pairs are reported once."""
    issue = MappingIssue(ref, field, reason)
    if issue not in issues:
        issues.append(issue)


def _first_record_timestamp(messages: list[FitMessage]) -> float | None:
    for number, fields in messages:
        if number == _RECORD_MESSAGE:
            stamp = fit_field(fields, _RECORD_MESSAGE, _TIMESTAMP_FIELD)
            if stamp is not None:
                return stamp
    return None


def _kept_records(
    ref: str, messages: list[FitMessage], issues: list[MappingIssue]
) -> list[tuple[float, Mapping[int, object]]]:
    """Return (seconds from time zero, fields) for each usable record.

    A record is skipped when it has no usable timestamp, when its timestamp is
    not strictly after the previous kept one, or when it lies beyond the stream
    span. The timestamp field gets at most one issue per reason: MISSING when any
    record lacks a usable timestamp, OUT_OF_RANGE when any record was skipped.
    """
    zero: float | None = None
    last: float | None = None
    missing = False
    out_of_range = False
    kept: list[tuple[float, Mapping[int, object]]] = []
    for number, fields in messages:
        if number != _RECORD_MESSAGE:
            continue
        stamp = fit_field(fields, _RECORD_MESSAGE, _TIMESTAMP_FIELD)
        if stamp is None:
            missing = True
            continue
        if zero is None:
            zero = stamp
        if last is not None and stamp <= last:
            out_of_range = True
            continue
        offset = stamp - zero
        if offset > MAX_STREAM_SPAN_S:
            out_of_range = True
            continue
        last = stamp
        kept.append((offset, fields))
    if missing:
        _add_issue(issues, ref, "timestamp", IssueReason.MISSING)
    if out_of_range:
        _add_issue(issues, ref, "timestamp", IssueReason.OUT_OF_RANGE)
    return kept


def _cadence(fields: Mapping[int, object]) -> float | None:
    """Whole cadence plus the fractional part when the device records one."""
    whole = fit_field(fields, _RECORD_MESSAGE, _CADENCE_FIELD)
    if whole is None:
        return None
    fraction = fit_field(fields, _RECORD_MESSAGE, _FRACTIONAL_CADENCE_FIELD)
    return whole + (fraction or 0.0)


def _add_channel(
    channels: dict[StreamChannel, tuple[float | None, ...]],
    ref: str,
    channel: StreamChannel,
    values: list[float | None],
    issues: list[MappingIssue],
) -> None:
    """Clean one channel; a channel without any usable point is dropped."""
    points, rejected = clean_series(channel, values)
    if rejected:
        _add_issue(issues, ref, channel.value, IssueReason.OUT_OF_RANGE)
    if any(point is not None for point in points):
        channels[channel] = points


def _stream_set(
    ref: str,
    provenance: Provenance,
    messages: list[FitMessage],
    issues: list[MappingIssue],
) -> ActivityStreamSet | None:
    kept = _kept_records(ref, messages, issues)
    if len(kept) > MAX_STREAM_POINTS:
        _add_issue(issues, ref, "record", IssueReason.OUT_OF_RANGE)
        return None
    # One record has no rate to show, and a time axis alone is not a stream set.
    if len(kept) < 2:
        return None
    rows = [fields for _, fields in kept]
    channels: dict[StreamChannel, tuple[float | None, ...]] = {
        StreamChannel.TIME_S: tuple(offset for offset, _ in kept)
    }
    for channel, field_number in _RECORD_CHANNEL_FIELDS:
        values = [fit_field(fields, _RECORD_MESSAGE, field_number) for fields in rows]
        _add_channel(channels, ref, channel, values, issues)
    _add_channel(
        channels,
        ref,
        StreamChannel.CADENCE_RPM,
        [_cadence(fields) for fields in rows],
        issues,
    )
    if len(channels) < 2:
        return None
    try:
        return ActivityStreamSet(
            provider_activity_id=ref,
            provenance=provenance,
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels=channels,
        )
    except TypeError, ValueError:
        _add_issue(issues, ref, "record", IssueReason.OUT_OF_RANGE)
        return None


def _lap_set(
    ref: str,
    provenance: Provenance,
    messages: list[FitMessage],
    issues: list[MappingIssue],
) -> ActivityLapSet | None:
    rows: list[Mapping[int, object]] = [
        fields for number, fields in messages if number == _LAP_MESSAGE
    ]
    if not rows:
        return None
    starts: list[tuple[float, Mapping[int, object]]] = []
    for fields in rows:
        start = fit_field(fields, _LAP_MESSAGE, _LAP_START_FIELD)
        if start is None:
            _add_issue(issues, ref, "start_time", IssueReason.MISSING)
            continue
        starts.append((start, fields))
    starts.sort(key=lambda item: item[0])
    # Time zero is the first record timestamp; without records, the first lap.
    zero = _first_record_timestamp(messages)
    if zero is None:
        if not starts:
            return None
        zero = starts[0][0]
    kept: list[ActivityLap] = []
    for start, fields in starts:
        lap = _lap(ref, start - zero, fields, issues)
        if lap is not None:
            kept.append(lap)
    if len(kept) > MAX_LAPS:
        _add_issue(issues, ref, "lap", IssueReason.OUT_OF_RANGE)
        del kept[MAX_LAPS:]
    if not kept:
        return None
    try:
        return ActivityLapSet(
            provider_activity_id=ref,
            provenance=provenance,
            origin=ActivityDetailOrigin.FETCH,
            lap_source=LapSource.DEVICE_LAPS,
            laps=tuple(
                replace(lap, index=position) for position, lap in enumerate(kept)
            ),
        )
    except TypeError, ValueError:
        _add_issue(issues, ref, "lap", IssueReason.OUT_OF_RANGE)
        return None


def _lap(
    ref: str,
    start_offset: float,
    fields: Mapping[int, object],
    issues: list[MappingIssue],
) -> ActivityLap | None:
    """Build one lap, or return None with the issue that drops it."""
    if start_offset < 0:
        _add_issue(issues, ref, "start_time", IssueReason.OUT_OF_RANGE)
        return None
    elapsed = fit_field(fields, _LAP_MESSAGE, _LAP_ELAPSED_FIELD)
    if elapsed is None:
        _add_issue(issues, ref, "total_elapsed_time", IssueReason.MISSING)
        return None
    metrics: dict[str, Any] = {}
    for name, field_number in _LAP_METRIC_FIELDS:
        value = fit_field(fields, _LAP_MESSAGE, field_number)
        if value is None:
            continue
        if _lap_accepts(name, value):
            metrics[name] = value
        else:
            _add_issue(issues, ref, name, IssueReason.OUT_OF_RANGE)
    try:
        return ActivityLap(
            index=0,
            kind=_lap_kind(fields),
            start_offset_s=start_offset,
            end_offset_s=start_offset + elapsed,
            **metrics,
        )
    except TypeError, ValueError:
        _add_issue(issues, ref, "lap", IssueReason.OUT_OF_RANGE)
        return None


def _lap_kind(fields: Mapping[int, object]) -> LapKind:
    intensity = fields.get(_LAP_INTENSITY_FIELD)
    if isinstance(intensity, int) and not isinstance(intensity, bool):
        return _LAP_KINDS.get(intensity, LapKind.LAP)
    return LapKind.LAP


def _lap_accepts(name: str, value: float) -> bool:
    """Whether ActivityLap accepts one metric, so its bounds are not repeated here."""
    metric: dict[str, Any] = {name: value}
    try:
        ActivityLap(
            index=0,
            kind=LapKind.LAP,
            start_offset_s=0.0,
            end_offset_s=0.0,
            **metric,
        )
    except TypeError, ValueError:
        return False
    return True
