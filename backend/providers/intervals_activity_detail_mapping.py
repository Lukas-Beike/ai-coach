"""Map Intervals.icu activity details to canonical detail sets.

The mapper is pure: it performs no I/O, logs nothing and never raises on
malformed provider input. A stream channel, lap or zone distribution that cannot
be mapped is dropped with a value-free MappingIssue, and the rest of the activity
is kept. Issues name the activity, the provider field and a reason only.

Two entry points share one private core, so a stored legacy record and a fresh
fetch of the same data map identically except for their origin:

* ``map_intervals_activity_detail`` maps a fresh ``GET /activity/{id}`` payload
  and the streams from ``backend.sync.activity_details.normalize_streams``.
* ``map_legacy_activity_detail`` maps one kv record written by
  ``ActivityDetailRefreshService.refresh``. Stored laps never kept the interval
  type, so their kind is always LAP.

Alias precedence: the first alias that yields a usable value wins. An alias that
rejects points or values still produces one issue for its channel, and the next
alias is tried. Arguments supplied by the caller (``recorded_by``,
``retrieved_at``) are checked and may raise, as in ``map_intervals_activities``;
provider data never does.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import pairwise
from typing import Any, Final

from backend.canonical.activity_detail import (
    MAX_LAP_NAME_LENGTH,
    MAX_LAPS,
    MAX_ZONES,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
    clean_series,
)
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import Provenance
from backend.canonical.validation import (
    MAX_ACTIVITY_DURATION_S,
    require_aware_datetime,
    require_instance,
)
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.providers.intervals_activity_fields import activity_detail_laps
from backend.providers.intervals_activity_mapping import (
    INTERVALS_LABEL,
    MAX_ACTIVITY_ID_LENGTH,
)
from backend.providers.intervals_performance_fields import (
    HEART_RATE_ZONE_TIMES,
    INTENSITY,
    TRAINING_LOAD,
    WEIGHTED_AVG_WATTS,
    ZONE_TIMES,
)

# Version 1: first mapping of activity detail sets (streams, laps, zones).
# Version 2: maximum speed per lap.
MAPPER_VERSION: Final = 2

# 800 bits render to at most 241 decimal digits, far below Python's int-to-str
# digit limit, so wider integers are rejected before str() is called.
_MAX_ID_INT_BITS: Final = 4 * MAX_ACTIVITY_ID_LENGTH
_TIME_ALIASES: Final = ("time",)
_CHANNEL_ALIASES: Final[Mapping[StreamChannel, tuple[str, ...]]] = {
    StreamChannel.DISTANCE_M: ("distance",),
    StreamChannel.ALTITUDE_M: ("altitude",),
    StreamChannel.GRADE_PCT: ("grade_smooth", "grade"),
    StreamChannel.SPEED_MPS: ("velocity_smooth", "velocity", "speed"),
    StreamChannel.POWER_W: ("watts", "power"),
    StreamChannel.HEART_RATE_BPM: ("heartrate",),
    StreamChannel.CADENCE_RPM: ("cadence",),
    StreamChannel.TEMPERATURE_C: ("temperature",),
    StreamChannel.MOVING: ("moving",),
}
_KNOWN_STREAM_KEYS: Final = frozenset(_TIME_ALIASES).union(
    key for aliases in _CHANNEL_ALIASES.values() for key in aliases
)
# The canonical channel of each stream key the mappers read; other keys are dropped.
STREAM_KEY_CHANNELS: Final[Mapping[str, StreamChannel]] = {
    **dict.fromkeys(_TIME_ALIASES, StreamChannel.TIME_S),
    **{
        key: channel for channel, aliases in _CHANNEL_ALIASES.items() for key in aliases
    },
}
# Legacy records hold the projected lap keys, fresh rows the raw Intervals keys.
_LAP_METRIC_KEYS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("moving_duration_s", ("moving_time",)),
    ("distance_m", ("distance",)),
    ("avg_hr", ("average_heartrate",)),
    ("max_hr", ("max_heartrate",)),
    ("avg_power", ("average_watts",)),
    ("max_power", ("max_watts",)),
    (
        "normalized_power",
        ("weighted_average_watts", "normalized_power", WEIGHTED_AVG_WATTS),
    ),
    ("avg_cadence", ("average_cadence",)),
    ("avg_speed_mps", ("average_speed",)),
    ("max_speed_mps", ("max_speed",)),
    ("elevation_gain_m", ("total_elevation_gain",)),
    ("load", (TRAINING_LOAD,)),
    ("intensity_pct", (INTENSITY,)),
)
_LAP_KINDS: Final[Mapping[str, LapKind]] = {
    "work": LapKind.WORK,
    "recovery": LapKind.RECOVERY,
}
_ZONE_KEYS: Final = (
    (HEART_RATE_ZONE_TIMES, ZoneMetric.HEART_RATE),
    (ZONE_TIMES, ZoneMetric.POWER),
)
# Only Z1, Z2, ... buckets are positional; "SS" and other ids overlap them.
_ZONE_ID: Final = re.compile(r"Z\d+", re.ASCII)


def zone_times(value: object) -> list[object]:
    """Keep recorded zone durations as numbers or bounded ``{id, secs}`` items.

    Plain numbers are positional (Z1, Z2, ...), so an invalid entry stays as a
    None gap. Coach analysis reads this projection, so its output must not change.
    """
    if not isinstance(value, list):
        return []
    zones: list[object] = []
    for item in value[:MAX_ZONES]:
        if isinstance(item, dict):
            secs = _zone_number(item.get("secs"))
            if secs is not None:
                zones.append({"id": str(item.get("id") or "")[:20], "secs": secs})
        else:
            zones.append(_zone_number(item))
    return zones


def _zone_number(value: object) -> int | float | None:
    """Return a finite number as given; booleans, text and other types give None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@dataclass(frozen=True, slots=True)
class _Header:
    """Identity and provenance shared by every set of one provider activity."""

    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin


def map_intervals_activity_detail(
    detail: object,
    streams: object,
    *,
    recorded_by: RecordingOrigin,
    retrieved_at: datetime,
) -> MappingResult[ActivityDetailSet]:
    """Map a fresh activity payload and its normalized streams (origin FETCH)."""
    require_instance(recorded_by, RecordingOrigin, "recorded_by")
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(detail, dict):
        invalid = MappingIssue(None, "detail", IssueReason.INVALID_TYPE)
        return MappingResult(issues=(invalid,))
    activity_id, issue = _activity_id(detail.get("id"), "id", allow_int=True)
    if activity_id is None:
        return MappingResult(issues=(issue,) if issue is not None else ())
    return _map_detail(
        provider_activity_id=activity_id,
        origin=ActivityDetailOrigin.FETCH,
        recorded_by=recorded_by,
        retrieved_at=retrieved_at,
        streams=streams,
        resolution=StreamResolution.FULL,
        laps=activity_detail_laps(detail),
        lap_field="icu_intervals",
        activity=detail,
    )


def map_legacy_activity_detail(
    record: object, *, recorded_by: RecordingOrigin
) -> MappingResult[ActivityDetailSet]:
    """Map one stored kv record written by an earlier release (LEGACY_BACKFILL)."""
    require_instance(recorded_by, RecordingOrigin, "recorded_by")
    if not isinstance(record, dict):
        issue = MappingIssue(None, "record", IssueReason.INVALID_TYPE)
        return MappingResult(issues=(issue,))
    issues: list[MappingIssue] = []
    activity_id, id_issue = _activity_id(
        record.get("activity_id"), "activity_id", allow_int=False
    )
    if id_issue is not None:
        issues.append(id_issue)
    observed_at = _observed_at(record.get("observed_at"))
    if observed_at is None:
        issues.append(
            MappingIssue(activity_id, "observed_at", IssueReason.INVALID_TYPE)
        )
    activity = record.get("activity")
    if not isinstance(activity, dict):
        issues.append(MappingIssue(activity_id, "activity", IssueReason.INVALID_TYPE))
    if activity_id is None or observed_at is None or not isinstance(activity, dict):
        return MappingResult(issues=tuple(issues))
    # Records written before full_resolution existed were downsampled.
    resolution = (
        StreamResolution.FULL
        if record.get("full_resolution") is True
        else StreamResolution.DOWNSAMPLED
    )
    mapped = _map_detail(
        provider_activity_id=activity_id,
        origin=ActivityDetailOrigin.LEGACY_BACKFILL,
        recorded_by=recorded_by,
        retrieved_at=observed_at,
        streams=activity.get("streams"),
        resolution=resolution,
        laps=activity.get("laps"),
        lap_field="laps",
        activity=activity,
    )
    return MappingResult(records=mapped.records, issues=(*issues, *mapped.issues))


def map_intervals_summary_zones(
    summary: Mapping[str, object],
    *,
    provider_activity_id: str,
    provenance: Provenance,
) -> MappingResult[ZoneDistribution]:
    """Map the zone times of a current summary row of one Intervals.icu record.

    Same zone mapping as a fresh fetch (origin FETCH), with the record's own
    provenance; the summary carries no streams or laps.
    """
    header = _Header(
        provider_activity_id=provider_activity_id,
        provenance=provenance,
        origin=ActivityDetailOrigin.FETCH,
    )
    issues: list[MappingIssue] = []
    records = tuple(
        distribution
        for key, metric in _ZONE_KEYS
        if (distribution := _zone_distribution(header, summary, key, metric, issues))
        is not None
    )
    return MappingResult(records=records, issues=tuple(issues))


def _map_detail(
    *,
    provider_activity_id: str,
    origin: ActivityDetailOrigin,
    recorded_by: RecordingOrigin,
    retrieved_at: datetime,
    streams: object,
    resolution: StreamResolution,
    laps: object,
    lap_field: str,
    activity: Mapping[str, object],
) -> MappingResult[ActivityDetailSet]:
    header = _Header(
        provider_activity_id=provider_activity_id,
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=provider_activity_id,
            recorded_by=recorded_by,
            retrieved_at=retrieved_at,
            label=INTERVALS_LABEL,
        ),
        origin=origin,
    )
    issues: list[MappingIssue] = []
    records: list[ActivityDetailSet] = []
    if streams is not None:
        if isinstance(streams, dict):
            stream_set = _stream_set(header, streams, resolution, issues)
            if stream_set is not None:
                records.append(stream_set)
        else:
            issues.append(
                MappingIssue(provider_activity_id, "streams", IssueReason.INVALID_TYPE)
            )
    lap_set = _lap_set(header, laps, lap_field, issues)
    if lap_set is not None:
        records.append(lap_set)
    for key, metric in _ZONE_KEYS:
        distribution = _zone_distribution(header, activity, key, metric, issues)
        if distribution is not None:
            records.append(distribution)
    return MappingResult(records=tuple(records), issues=tuple(issues))


def _activity_id(
    value: object, field: str, *, allow_int: bool
) -> tuple[str | None, MappingIssue | None]:
    """Return the activity id as text, or None with the issue that explains it."""
    accepted: tuple[type, ...] = (str, int) if allow_int else (str,)
    if value is None:
        return None, MappingIssue(None, field, IssueReason.MISSING)
    if isinstance(value, bool) or not isinstance(value, accepted):
        return None, MappingIssue(None, field, IssueReason.INVALID_TYPE)
    if isinstance(value, int) and value.bit_length() > _MAX_ID_INT_BITS:
        return None, MappingIssue(None, field, IssueReason.OUT_OF_RANGE)
    text = str(value).strip()
    if not text:
        return None, MappingIssue(None, field, IssueReason.MISSING)
    if len(text) > MAX_ACTIVITY_ID_LENGTH:
        return None, MappingIssue(None, field, IssueReason.OUT_OF_RANGE)
    return text, None


def _observed_at(value: object) -> datetime | None:
    """Return the stored observation time when it is ISO text with an offset."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _stream_set(
    header: _Header,
    streams: Mapping[str, object],
    resolution: StreamResolution,
    issues: list[MappingIssue],
) -> ActivityStreamSet | None:
    ref = header.provider_activity_id
    # An activity fetched without streams carries no stream data to report.
    if not any(key in streams for key in _KNOWN_STREAM_KEYS):
        return None
    time_points, issue = _pick_channel(
        ref, StreamChannel.TIME_S, _TIME_ALIASES, streams, length=None
    )
    if time_points is None:
        issues.append(issue or MappingIssue(ref, "time", IssueReason.MISSING))
        return None
    # A gap or a rejected point leaves the time axis unusable as a whole.
    if issue is not None or any(point is None for point in time_points):
        issues.append(issue or MappingIssue(ref, "time", IssueReason.INVALID_NUMBER))
        return None
    axis = [point for point in time_points if point is not None]
    if any(right <= left for left, right in pairwise(axis)):
        issues.append(MappingIssue(ref, "time", IssueReason.OUT_OF_RANGE))
        return None
    channels: dict[StreamChannel, tuple[float | None, ...]] = {
        StreamChannel.TIME_S: time_points
    }
    for channel, aliases in _CHANNEL_ALIASES.items():
        points, issue = _pick_channel(
            ref, channel, aliases, streams, length=len(time_points)
        )
        if issue is not None:
            issues.append(issue)
        if points is not None:
            channels[channel] = points
    # A time axis without any other channel is not a stream set.
    if len(channels) < 2:
        return None
    try:
        return ActivityStreamSet(
            provider_activity_id=ref,
            provenance=header.provenance,
            origin=header.origin,
            resolution=resolution,
            channels=channels,
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, "time", IssueReason.OUT_OF_RANGE))
        return None


def _pick_channel(
    ref: str,
    channel: StreamChannel,
    aliases: tuple[str, ...],
    streams: Mapping[str, object],
    *,
    length: int | None,
) -> tuple[tuple[float | None, ...] | None, MappingIssue | None]:
    """Return the first alias with a usable point, and the one issue to report.

    An alias that is not a list, or whose length differs from ``length``, is
    skipped. Points that ``clean_series`` rejects become gaps; the first alias
    with such a problem supplies the single issue for the channel.
    """
    issue: MappingIssue | None = None
    for key in aliases:
        if key not in streams:
            continue
        points, alias_issue = _alias_points(
            ref, channel, key, streams[key], length=length
        )
        if issue is None:
            issue = alias_issue
        if points is not None:
            return points, issue
    return None, issue


def _alias_points(
    ref: str,
    channel: StreamChannel,
    key: str,
    raw: object,
    *,
    length: int | None,
) -> tuple[tuple[float | None, ...] | None, MappingIssue | None]:
    """Return one alias's points if any is usable, and that alias's issue."""
    if not isinstance(raw, list) or (length is not None and len(raw) != length):
        return None, MappingIssue(ref, key, IssueReason.INVALID_TYPE)
    # clean_series rejects booleans, so moving flags become 1.0 and 0.0 first.
    values = (
        [_moving_value(value) for value in raw]
        if channel is StreamChannel.MOVING
        else raw
    )
    points, rejected = clean_series(channel, values)
    issue = MappingIssue(ref, key, IssueReason.OUT_OF_RANGE) if rejected else None
    if any(point is not None for point in points):
        return points, issue
    return None, issue


def _moving_value(value: object) -> object:
    if value is True:
        return 1.0
    if value is False:
        return 0.0
    return value


def _lap_set(
    header: _Header,
    laps: object,
    lap_field: str,
    issues: list[MappingIssue],
) -> ActivityLapSet | None:
    ref = header.provider_activity_id
    if laps is None:
        return None
    if not isinstance(laps, list):
        issues.append(MappingIssue(ref, lap_field, IssueReason.INVALID_TYPE))
        return None
    kept: list[ActivityLap] = []
    for row in laps:
        lap = _lap(row, ref, lap_field, issues)
        if lap is not None:
            kept.append(lap)
    # The sort is stable, so laps that start together keep their provider order.
    kept.sort(key=lambda lap: lap.start_offset_s)
    if len(kept) > MAX_LAPS:
        issues.append(MappingIssue(ref, lap_field, IssueReason.OUT_OF_RANGE))
        del kept[MAX_LAPS:]
    if not kept:
        return None
    try:
        return ActivityLapSet(
            provider_activity_id=ref,
            provenance=header.provenance,
            origin=header.origin,
            lap_source=LapSource.PROVIDER_INTERVALS,
            laps=tuple(
                replace(lap, index=position) for position, lap in enumerate(kept)
            ),
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, lap_field, IssueReason.OUT_OF_RANGE))
        return None


def _lap(
    row: object, ref: str, lap_field: str, issues: list[MappingIssue]
) -> ActivityLap | None:
    """Map one lap row; its index is set by the caller once laps are sorted."""
    if not isinstance(row, dict):
        issues.append(MappingIssue(ref, lap_field, IssueReason.INVALID_TYPE))
        return None
    start = _lap_offset(row, "start_time", ref, issues)
    end = _lap_offset(row, "end_time", ref, issues)
    if start is None or end is None:
        return None
    if end < start:
        issues.append(MappingIssue(ref, "end_time", IssueReason.OUT_OF_RANGE))
        return None
    try:
        return ActivityLap(
            index=0,
            kind=_lap_kind(row),
            start_offset_s=start,
            end_offset_s=end,
            name=_lap_name(row, ref, issues),
            **_lap_metrics(row, ref, issues),
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, lap_field, IssueReason.OUT_OF_RANGE))
        return None


def _lap_offset(
    row: Mapping[str, object], key: str, ref: str, issues: list[MappingIssue]
) -> float | None:
    value = row.get(key)
    number = coerce_number(value)
    if number is not None and 0.0 <= number <= MAX_ACTIVITY_DURATION_S:
        return number
    if value is None:
        reason = IssueReason.MISSING
    elif number is None:
        reason = IssueReason.INVALID_NUMBER
    else:
        reason = IssueReason.OUT_OF_RANGE
    issues.append(MappingIssue(ref, key, reason))
    return None


def _lap_kind(row: Mapping[str, object]) -> LapKind:
    value = row.get("type")
    if isinstance(value, str):
        return _LAP_KINDS.get(value.casefold(), LapKind.LAP)
    return LapKind.LAP


def _lap_name(
    row: Mapping[str, object], ref: str, issues: list[MappingIssue]
) -> str | None:
    value = row.get("name")
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(MappingIssue(ref, "name", IssueReason.INVALID_TYPE))
        return None
    return value.strip()[:MAX_LAP_NAME_LENGTH] or None


def _lap_metrics(
    row: Mapping[str, object], ref: str, issues: list[MappingIssue]
) -> dict[str, float]:
    """Keep each metric that ActivityLap accepts; drop the others with an issue."""
    metrics: dict[str, float] = {}
    for name, keys in _LAP_METRIC_KEYS:
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            number = _lap_metric(name, value)
            if isinstance(number, IssueReason):
                issues.append(MappingIssue(ref, key, number))
                continue
            metrics[name] = number
            break
    return metrics


def _lap_metric(name: str, value: object) -> float | IssueReason:
    """Return one accepted lap metric, or the reason it is dropped."""
    number = coerce_number(value)
    if number is None:
        return IssueReason.INVALID_NUMBER
    if name == "intensity_pct":
        number = _intensity_pct(number)
    if not _lap_accepts(name, number):
        return IssueReason.OUT_OF_RANGE
    return number


def _intensity_pct(value: float) -> float:
    """Intervals reports intensity as a fraction or a percentage; keep percent."""
    # Same rule as performance.activity_validation.activity_intensity.
    if 0 < value <= 2:
        return round(value * 100, 1)
    return value


def _lap_accepts(name: str, value: float) -> bool:
    """Whether ActivityLap accepts one metric, so its bounds are not repeated here."""
    # ActivityLap takes one keyword per metric; the name is one of its float fields.
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


def _zone_distribution(
    header: _Header,
    activity: Mapping[str, object],
    key: str,
    metric: ZoneMetric,
    issues: list[MappingIssue],
) -> ZoneDistribution | None:
    ref = header.provider_activity_id
    buckets: list[ZoneBucket] = []
    unsupported = False
    if not _zone_payload_valid(activity.get(key), ref, key, issues):
        return None
    for item in zone_times(activity.get(key)):
        if item is None:
            # A gap would shift the positions of the zones after it.
            issues.append(MappingIssue(ref, key, IssueReason.INVALID_NUMBER))
            return None
        if isinstance(item, dict):
            zone_id = str(item["id"])
            if not _ZONE_ID.fullmatch(zone_id):
                unsupported = True
                continue
            label, seconds = zone_id, item["secs"]
        else:
            label, seconds = None, item
        try:
            buckets.append(
                ZoneBucket(index=len(buckets) + 1, seconds=seconds, label=label)
            )
        except TypeError, ValueError:
            issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
            return None
    if unsupported:
        issues.append(MappingIssue(ref, key, IssueReason.UNSUPPORTED))
    if not buckets:
        return None
    try:
        return ZoneDistribution(
            provider_activity_id=ref,
            provenance=header.provenance,
            origin=header.origin,
            metric=metric,
            boundary_source=ZoneBoundarySource.UNKNOWN,
            buckets=tuple(buckets),
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
        return None


def _zone_payload_valid(
    value: object, ref: str, key: str, issues: list[MappingIssue]
) -> bool:
    """Report what ``zone_times`` would drop silently: a non-list or a bad bucket."""
    if value is None:
        return True
    if not isinstance(value, list):
        issues.append(MappingIssue(ref, key, IssueReason.INVALID_TYPE))
        return False
    if any(_bad_positional_bucket(item) for item in value[:MAX_ZONES]):
        # Dropping one Z bucket would renumber the zones after it.
        issues.append(MappingIssue(ref, key, IssueReason.INVALID_NUMBER))
        return False
    return True


def _bad_positional_bucket(item: object) -> bool:
    """Whether a ``Z<n>`` bucket has invalid seconds; other ids are skipped anyway."""
    return (
        isinstance(item, dict)
        and _ZONE_ID.fullmatch(str(item.get("id") or "")[:20]) is not None
        and _zone_number(item.get("secs")) is None
    )
