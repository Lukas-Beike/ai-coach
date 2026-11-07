"""Map Garmin Connect activity details to canonical detail sets.

The input is the dict returned by ``backend.providers.garmin.collect_garmin_activity_detail``:
``details`` (get_activity_details), ``splits`` (get_activity_splits), ``hr_zones``
and ``power_zones`` (get_activity_hr/power_in_timezones), ``exercise_sets``
(get_activity_exercise_sets, strength activities only) and ``fit`` (the original
FIT file from the Personal API). A part that is absent yields no set
and no issue; a part that is present but malformed yields one value-free issue
and no set for that part.

A decodable FIT file wins over the JSON parts of the same kind: its record
streams (full resolution) replace the downsampled ``details`` charts and its
device laps replace ``splits``. The FIT sets are mapped by
``fit_activity_detail_mapping`` under the Garmin provenance; ``details`` and
``splits`` remain the fallback for a kind the file does not yield.

Strength sets go the other way: Garmin's ``exercise_sets`` include the athlete's
corrections in Connect, which the original file lacks, so they win over the
file's set messages, which stay the fallback. Each set takes the exercise with
the highest ``probability``; its ``category`` maps to the FIT exercise category
of the same name (else ``other``, keeping the code as the exercise name when no
name is given) and ``name`` is kept only as an upper-case code. ``weight`` is
read in grams (unverified on a live payload, like the FIT path) and 0 means no
external load; ``duration`` is in seconds. ``startTime`` is not mapped, as the
part carries no activity start to measure it from.

The mapper is pure: it performs no I/O, logs nothing and never raises on
malformed provider input. Issues name the activity, the provider field and a
reason only. Caller arguments (``recorded_by``, ``retrieved_at``) are checked
and may raise, as in the Intervals mapper.

The canonical cadence counts one leg in rpm, like Intervals and FIT. Garmin's
``directRunCadence`` stream already counts one leg (``directDoubleCadence`` is the
two-leg value), so it is kept as reported. The unit of the lap
``averageRunCadence`` is not verified, so lap run cadence is not mapped.

Offsets use elapsed time (``sumElapsedDuration``, lap ``elapsedDuration``) so
they line up with the activity start like the Intervals streams; the timer
values (``sumDuration``, lap ``duration``) are the fallback when elapsed time is
absent, which only differs after a pause.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from itertools import pairwise
from typing import Any, Final, cast

from backend.canonical.activity_detail import (
    EXERCISE_NAME_PATTERN,
    MAX_LAPS,
    MAX_STRENGTH_SETS,
    MAX_ZONES,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ActivityStrengthSet,
    ActivityStrengthSetSet,
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
    ExerciseCategory,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
    StrengthSetSource,
    StrengthSetType,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from backend.providers.garmin_activity_mapping import GARMIN_LABEL

# Version 1: first mapping of Garmin activity detail sets (streams, laps, zones).
# Version 2: maximum speed per lap.
# Version 3: FIT record streams and device laps win over charts and splits.
# Version 4: executed strength sets from exercise sets, else FIT set messages.
MAPPER_VERSION: Final = 4

# Same limit as the Intervals mapper; kept local so providers do not import each other.
MAX_GARMIN_ACTIVITY_ID_LENGTH: Final = 200

_TIME_KEY: Final = "sumDuration"
_ELAPSED_TIME_KEY: Final = "sumElapsedDuration"
_BIKE_CADENCE_KEY: Final = "directBikeCadence"
_RUN_CADENCE_KEY: Final = "directRunCadence"
# Garmin metric key -> canonical channel. Keys not listed here are ignored.
_STREAM_KEYS: Final[Mapping[str, StreamChannel]] = {
    _TIME_KEY: StreamChannel.TIME_S,
    "sumDistance": StreamChannel.DISTANCE_M,
    "directElevation": StreamChannel.ALTITUDE_M,
    "directSpeed": StreamChannel.SPEED_MPS,
    "directPower": StreamChannel.POWER_W,
    "directHeartRate": StreamChannel.HEART_RATE_BPM,
    "directAirTemperature": StreamChannel.TEMPERATURE_C,
}
_KNOWN_KEYS: Final = frozenset(_STREAM_KEYS) | {
    _ELAPSED_TIME_KEY,
    _BIKE_CADENCE_KEY,
    _RUN_CADENCE_KEY,
}
_LAP_DURATION_KEYS: Final = ("elapsedDuration", "duration")
# Garmin lap key -> ActivityLap field. Cadence is handled separately.
_LAP_METRIC_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("movingDuration", "moving_duration_s"),
    ("distance", "distance_m"),
    ("averageHR", "avg_hr"),
    ("maxHR", "max_hr"),
    ("averagePower", "avg_power"),
    ("maxPower", "max_power"),
    ("normalizedPower", "normalized_power"),
    ("averageSpeed", "avg_speed_mps"),
    ("maxSpeed", "max_speed_mps"),
    ("elevationGain", "elevation_gain_m"),
)
_LAP_CADENCE_KEY: Final = "averageBikeCadence"
_ZONE_KEYS: Final = (
    ("hr_zones", ZoneMetric.HEART_RATE),
    ("power_zones", ZoneMetric.POWER),
)
_EXERCISE_SETS_KEY: Final = "exercise_sets"
_SET_TYPES: Final[Mapping[str, StrengthSetType]] = {
    "ACTIVE": StrengthSetType.ACTIVE,
    "REST": StrengthSetType.REST,
}
_GRAMS_PER_KG: Final = 1000.0


def map_garmin_activity_detail(
    collected: object,
    *,
    recorded_by: RecordingOrigin,
    retrieved_at: datetime,
) -> MappingResult[ActivityDetailSet]:
    """Map one collected Garmin activity detail (origin FETCH)."""
    require_instance(recorded_by, RecordingOrigin, "recorded_by")
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(collected, dict):
        invalid = MappingIssue(None, "collected", IssueReason.INVALID_TYPE)
        return MappingResult(issues=(invalid,))
    activity_id, issue = _activity_id(collected.get("activity_id"))
    if activity_id is None:
        return MappingResult(issues=(issue,) if issue is not None else ())
    provenance = Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=activity_id,
        recorded_by=recorded_by,
        retrieved_at=retrieved_at,
        label=GARMIN_LABEL,
    )
    issues: list[MappingIssue] = []
    records: list[ActivityDetailSet] = []
    fit_sets = _fit_sets(activity_id, provenance, collected.get("fit"), issues)
    stream_set = fit_sets.get(ActivityStreamSet) or _stream_set(
        activity_id, provenance, collected.get("details"), issues
    )
    if stream_set is not None:
        records.append(stream_set)
    lap_set = fit_sets.get(ActivityLapSet) or _lap_set(
        activity_id, provenance, collected.get("splits"), issues
    )
    if lap_set is not None:
        records.append(lap_set)
    for key, metric in _ZONE_KEYS:
        distribution = _zone_distribution(
            activity_id, provenance, collected.get(key), key, metric, issues
        )
        if distribution is not None:
            records.append(distribution)
    strength_set = _strength_set_set(
        activity_id, provenance, collected.get(_EXERCISE_SETS_KEY), issues
    ) or fit_sets.get(ActivityStrengthSetSet)
    if strength_set is not None:
        records.append(strength_set)
    return MappingResult(records=tuple(records), issues=tuple(issues))


def _fit_sets(
    ref: str,
    provenance: Provenance,
    data: object,
    issues: list[MappingIssue],
) -> dict[type, ActivityDetailSet]:
    """Map the FIT part into its stream, lap and strength sets, keyed by set type."""
    if data is None:
        return {}
    mapped = map_fit_activity_detail(
        data, provider_activity_id=ref, provenance=provenance
    )
    issues.extend(mapped.issues)
    return {type(record): record for record in mapped.records}


def _activity_id(value: object) -> tuple[str | None, MappingIssue | None]:
    """Return the activity id as text, or None with the issue that explains it."""
    if value is None:
        return None, MappingIssue(None, "activity_id", IssueReason.MISSING)
    if not isinstance(value, str):
        return None, MappingIssue(None, "activity_id", IssueReason.INVALID_TYPE)
    text = value.strip()
    if not text:
        return None, MappingIssue(None, "activity_id", IssueReason.MISSING)
    if len(text) > MAX_GARMIN_ACTIVITY_ID_LENGTH:
        return None, MappingIssue(None, "activity_id", IssueReason.OUT_OF_RANGE)
    return text, None


def _shape_reason(value: object) -> IssueReason:
    return IssueReason.MISSING if value is None else IssueReason.INVALID_TYPE


def _stream_set(
    ref: str,
    provenance: Provenance,
    details: object,
    issues: list[MappingIssue],
) -> ActivityStreamSet | None:
    if details is None:
        return None
    if not isinstance(details, dict):
        issues.append(MappingIssue(ref, "details", IssueReason.INVALID_TYPE))
        return None
    columns = _metric_columns(ref, details, issues)
    if columns is None:
        return None
    time_key = _ELAPSED_TIME_KEY if _ELAPSED_TIME_KEY in columns else _TIME_KEY
    time_points, time_issue = _time_axis(ref, time_key, columns)
    if time_points is None:
        issues.append(time_issue or MappingIssue(ref, time_key, IssueReason.MISSING))
        return None
    axis = [point for point in time_points if point is not None]
    if any(right <= left for left, right in pairwise(axis)):
        issues.append(MappingIssue(ref, time_key, IssueReason.OUT_OF_RANGE))
        return None
    channels = _stream_channels(ref, time_points, columns, issues)
    # A time axis without any other channel is not a stream set.
    if len(channels) < 2:
        return None
    try:
        return ActivityStreamSet(
            provider_activity_id=ref,
            provenance=provenance,
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.DOWNSAMPLED,
            channels=channels,
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, time_key, IssueReason.OUT_OF_RANGE))
        return None


def _stream_channels(
    ref: str,
    time_points: tuple[float | None, ...],
    columns: Mapping[str, list[object]],
    issues: list[MappingIssue],
) -> dict[StreamChannel, tuple[float | None, ...]]:
    channels: dict[StreamChannel, tuple[float | None, ...]] = {
        StreamChannel.TIME_S: time_points
    }
    for key, channel in _STREAM_KEYS.items():
        if channel is StreamChannel.TIME_S or key not in columns:
            continue
        points = _channel_points(ref, key, channel, columns[key], issues)
        if points is not None:
            channels[channel] = points
    cadence = _cadence_points(ref, columns, issues)
    if cadence is not None:
        channels[StreamChannel.CADENCE_RPM] = cadence
    return channels


def _metric_columns(
    ref: str, details: Mapping[str, object], issues: list[MappingIssue]
) -> dict[str, list[object]] | None:
    """Return one value column per known Garmin key, aligned to the rows.

    A malformed descriptor or row makes the whole stream set unusable, because
    the position of every value depends on the descriptor layout.
    """
    descriptors = details.get("metricDescriptors")
    rows = details.get("activityDetailMetrics")
    if not isinstance(descriptors, list):
        issues.append(
            MappingIssue(ref, "metricDescriptors", _shape_reason(descriptors))
        )
        return None
    if not isinstance(rows, list):
        issues.append(MappingIssue(ref, "activityDetailMetrics", _shape_reason(rows)))
        return None
    positions = _known_positions(ref, descriptors, issues)
    if positions is None or not any(
        key in positions for key in (*_STREAM_KEYS, _ELAPSED_TIME_KEY)
    ):
        return None
    # Only the known columns must be present; unknown trailing metrics may be short.
    width = max(positions.values()) + 1
    columns: dict[str, list[object]] = {key: [] for key in positions}
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, list) or len(metrics) < width:
            issues.append(
                MappingIssue(ref, "activityDetailMetrics", IssueReason.INVALID_TYPE)
            )
            return None
        for key, index in positions.items():
            columns[key].append(metrics[index])
    return columns


def _known_positions(
    ref: str, descriptors: list[object], issues: list[MappingIssue]
) -> dict[str, int] | None:
    """Map each known key to its first metrics index; None on a malformed descriptor."""
    positions: dict[str, int] = {}
    for descriptor in descriptors:
        parsed = _descriptor(descriptor)
        if parsed is None:
            issues.append(
                MappingIssue(ref, "metricDescriptors", IssueReason.INVALID_TYPE)
            )
            return None
        key, index = parsed
        if key in _KNOWN_KEYS and key not in positions:
            positions[key] = index
    return positions


def _descriptor(value: object) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    key = value.get("key")
    index = value.get("metricsIndex")
    if (
        not isinstance(key, str)
        or isinstance(index, bool)
        or not isinstance(index, int)
    ):
        return None
    if index < 0:
        return None
    return key, index


def _time_axis(
    ref: str, time_key: str, columns: Mapping[str, list[object]]
) -> tuple[tuple[float | None, ...] | None, MappingIssue | None]:
    """Return the cleaned time axis, or None with the one issue to report."""
    column = columns.get(time_key)
    if column is None:
        return None, MappingIssue(ref, time_key, IssueReason.MISSING)
    if not column:
        return None, MappingIssue(ref, "activityDetailMetrics", IssueReason.MISSING)
    points, rejected = clean_series(StreamChannel.TIME_S, column)
    if rejected:
        return None, MappingIssue(ref, time_key, IssueReason.OUT_OF_RANGE)
    if any(point is None for point in points):
        return None, MappingIssue(ref, time_key, IssueReason.INVALID_NUMBER)
    return points, None


def _channel_points(
    ref: str,
    key: str,
    channel: StreamChannel,
    column: list[object],
    issues: list[MappingIssue],
) -> tuple[float | None, ...] | None:
    """Clean one channel; one value-free issue when any value is rejected."""
    points, rejected = clean_series(channel, column)
    if rejected:
        issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
    if all(point is None for point in points):
        return None
    return points


def _cadence_points(
    ref: str, columns: Mapping[str, list[object]], issues: list[MappingIssue]
) -> tuple[float | None, ...] | None:
    """Bike cadence wins; run cadence is used only when bike has no usable point."""
    bike = columns.get(_BIKE_CADENCE_KEY)
    if bike is not None:
        points = _channel_points(
            ref, _BIKE_CADENCE_KEY, StreamChannel.CADENCE_RPM, bike, issues
        )
        if points is not None:
            return points
    run = columns.get(_RUN_CADENCE_KEY)
    if run is None:
        return None
    return _channel_points(
        ref, _RUN_CADENCE_KEY, StreamChannel.CADENCE_RPM, run, issues
    )


def _lap_set(
    ref: str,
    provenance: Provenance,
    splits: object,
    issues: list[MappingIssue],
) -> ActivityLapSet | None:
    if splits is None:
        return None
    if not isinstance(splits, dict):
        issues.append(MappingIssue(ref, "splits", IssueReason.INVALID_TYPE))
        return None
    rows = splits.get("lapDTOs")
    if not isinstance(rows, list):
        issues.append(MappingIssue(ref, "lapDTOs", _shape_reason(rows)))
        return None
    kept: list[ActivityLap] = []
    elapsed = 0.0
    for lap_row in _ordered_laps(ref, rows, issues):
        duration = _duration(lap_row, ref, issues)
        if duration is None:
            # Every later offset depends on this lap, so the laps stop here.
            break
        start = elapsed
        end = start + duration
        if end > MAX_ACTIVITY_DURATION_S:
            issues.append(MappingIssue(ref, "duration", IssueReason.OUT_OF_RANGE))
            break
        metrics = _lap_metrics(lap_row, ref, issues)
        cadence = _lap_cadence(lap_row, ref, issues)
        if cadence is not None:
            metrics["avg_cadence"] = cadence
        try:
            lap = ActivityLap(
                index=0,
                kind=LapKind.LAP,
                start_offset_s=start,
                end_offset_s=end,
                **metrics,
            )
        except TypeError, ValueError:
            issues.append(MappingIssue(ref, "duration", IssueReason.OUT_OF_RANGE))
            continue
        kept.append(lap)
        elapsed = end
    if len(kept) > MAX_LAPS:
        issues.append(MappingIssue(ref, "lapDTOs", IssueReason.OUT_OF_RANGE))
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
                cast(ActivityLap, replace(lap, index=position))
                for position, lap in enumerate(kept)
            ),
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, "lapDTOs", IssueReason.OUT_OF_RANGE))
        return None


def _ordered_laps(
    ref: str, rows: list[object], issues: list[MappingIssue]
) -> list[Mapping[str, object]]:
    """Return lap rows in device order (lapIndex when every row has one)."""
    laps: list[Mapping[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            laps.append(row)
        else:
            issues.append(MappingIssue(ref, "lapDTOs", IssueReason.INVALID_TYPE))
    indexes = [_lap_index(lap) for lap in laps]
    if any(index is None for index in indexes):
        return laps
    order = sorted(range(len(laps)), key=lambda position: indexes[position] or 0)
    return [laps[position] for position in order]


def _lap_index(row: Mapping[str, object]) -> int | None:
    value = row.get("lapIndex")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _duration(
    row: Mapping[str, object], ref: str, issues: list[MappingIssue]
) -> float | None:
    value = next(
        (row[key] for key in _LAP_DURATION_KEYS if row.get(key) is not None), None
    )
    number = coerce_number(value)
    if number is not None and 0.0 <= number <= MAX_ACTIVITY_DURATION_S:
        return number
    if value is None:
        reason = IssueReason.MISSING
    elif number is None:
        reason = IssueReason.INVALID_NUMBER
    else:
        reason = IssueReason.OUT_OF_RANGE
    issues.append(MappingIssue(ref, "duration", reason))
    return None


def _lap_metrics(
    row: Mapping[str, object], ref: str, issues: list[MappingIssue]
) -> dict[str, Any]:
    """Keep each metric that ActivityLap accepts; drop the others with an issue."""
    metrics: dict[str, Any] = {}
    for key, name in _LAP_METRIC_KEYS:
        value = row.get(key)
        if value is None:
            continue
        number = coerce_number(value)
        if number is None:
            issues.append(MappingIssue(ref, key, IssueReason.INVALID_NUMBER))
        elif not _lap_accepts(name, number):
            issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
        else:
            metrics[name] = number
    return metrics


def _lap_cadence(
    row: Mapping[str, object], ref: str, issues: list[MappingIssue]
) -> float | None:
    """Bike lap cadence in rpm; lap run cadence is not mapped (see module docstring)."""
    value = row.get(_LAP_CADENCE_KEY)
    if value is None:
        return None
    number = coerce_number(value)
    if number is None:
        issues.append(MappingIssue(ref, _LAP_CADENCE_KEY, IssueReason.INVALID_NUMBER))
        return None
    if not _lap_accepts("avg_cadence", number):
        issues.append(MappingIssue(ref, _LAP_CADENCE_KEY, IssueReason.OUT_OF_RANGE))
        return None
    return number


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


def _zone_distribution(
    ref: str,
    provenance: Provenance,
    rows: object,
    key: str,
    metric: ZoneMetric,
    issues: list[MappingIssue],
) -> ZoneDistribution | None:
    if rows is None:
        return None
    if not isinstance(rows, list):
        issues.append(MappingIssue(ref, key, IssueReason.INVALID_TYPE))
        return None
    entries = _zone_entries(ref, rows, key, issues)
    if not entries:
        return None
    lows = [low for _, _, low in entries]
    # Provider boundaries apply only when every zone reports a low boundary and
    # they rise with the zone number; otherwise the seconds stay, bounds unknown.
    provider_bounds = all(low is not None for low in lows) and all(
        left is not None and right is not None and left < right
        for left, right in pairwise(lows)
    )
    try:
        return ZoneDistribution(
            provider_activity_id=ref,
            provenance=provenance,
            origin=ActivityDetailOrigin.FETCH,
            metric=metric,
            boundary_source=(
                ZoneBoundarySource.PROVIDER_REPORTED
                if provider_bounds
                else ZoneBoundarySource.UNKNOWN
            ),
            buckets=_zone_buckets(entries, provider_bounds),
        )
    except TypeError, ValueError:
        issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
        return None


def _zone_entries(
    ref: str, rows: list[object], key: str, issues: list[MappingIssue]
) -> list[tuple[int, float, float | None]] | None:
    """Return the zones numbered 1..n in order, or None with the one issue to report."""
    entries: list[tuple[int, float, float | None]] = []
    for row in rows:
        entry = _zone_entry(row)
        if isinstance(entry, IssueReason):
            # One bad zone drops the whole distribution; a gap would renumber the rest.
            issues.append(MappingIssue(ref, key, entry))
            return None
        entries.append(entry)
    entries.sort(key=lambda entry: entry[0])
    numbers = [number for number, _, _ in entries]
    if len(entries) > MAX_ZONES or numbers != list(range(1, len(entries) + 1)):
        issues.append(MappingIssue(ref, key, IssueReason.OUT_OF_RANGE))
        return None
    return entries


def _zone_buckets(
    entries: list[tuple[int, float, float | None]], provider_bounds: bool
) -> tuple[ZoneBucket, ...]:
    """Build the buckets; ZoneBucket raises on a value it does not accept."""
    lows = [low for _, _, low in entries] if provider_bounds else [None] * len(entries)
    uppers = [*lows[1:], None]
    return tuple(
        ZoneBucket(index=position + 1, seconds=seconds, lower=lower, upper=upper)
        for position, ((_, seconds, _), lower, upper) in enumerate(
            zip(entries, lows, uppers, strict=True)
        )
    )


def _zone_entry(row: object) -> tuple[int, float, float | None] | IssueReason:
    """Return (zone number, seconds, low boundary) or the reason the zone is unusable."""
    if not isinstance(row, dict):
        return IssueReason.INVALID_TYPE
    number = row.get("zoneNumber")
    if isinstance(number, bool) or not isinstance(number, int):
        return IssueReason.INVALID_TYPE
    if not 1 <= number <= MAX_ZONES:
        return IssueReason.OUT_OF_RANGE
    seconds = coerce_number(row.get("secsInZone"))
    if seconds is None:
        return IssueReason.INVALID_NUMBER
    if not 0.0 <= seconds <= MAX_ACTIVITY_DURATION_S:
        return IssueReason.OUT_OF_RANGE
    return number, seconds, coerce_number(row.get("zoneLowBoundary"))


def _strength_set_set(
    ref: str,
    provenance: Provenance,
    payload: object,
    issues: list[MappingIssue],
) -> ActivityStrengthSetSet | None:
    """Map Garmin's exercise sets; None when the part is absent or holds no set."""
    if payload is None:
        return None
    rows = payload.get("exerciseSets") if isinstance(payload, dict) else payload
    if rows is None:
        return None
    if not isinstance(rows, list):
        issues.append(MappingIssue(ref, _EXERCISE_SETS_KEY, IssueReason.INVALID_TYPE))
        return None
    kept: list[ActivityStrengthSet] = []
    for row in rows:
        item = _exercise_set(ref, len(kept), row, issues)
        if item is None:
            continue
        if len(kept) == MAX_STRENGTH_SETS:
            _add_set_issue(issues, ref, "exerciseSets", IssueReason.OUT_OF_RANGE)
            break
        kept.append(item)
    if not kept:
        return None
    return ActivityStrengthSetSet(
        provider_activity_id=ref,
        provenance=provenance,
        origin=ActivityDetailOrigin.FETCH,
        source=StrengthSetSource.GARMIN_EXERCISE_SETS,
        sets=tuple(kept),
    )


def _add_set_issue(
    issues: list[MappingIssue], ref: str, field: str, reason: IssueReason
) -> None:
    issue = MappingIssue(ref, field, reason)
    if issue not in issues:
        issues.append(issue)


def _exercise_set(
    ref: str, index: int, row: object, issues: list[MappingIssue]
) -> ActivityStrengthSet | None:
    """Build one set, or return None with the issue that drops it."""
    if not isinstance(row, dict):
        _add_set_issue(issues, ref, "exerciseSets", IssueReason.INVALID_TYPE)
        return None
    set_type = _SET_TYPES.get(str(row.get("setType") or "").upper())
    if set_type is None:
        _add_set_issue(issues, ref, "setType", _shape_reason(row.get("setType")))
        return None
    weight_g = coerce_number(row.get("weight"))
    values: dict[str, Any] = {
        "reps": _whole_number(row.get("repetitionCount")),
        "weight_kg": weight_g / _GRAMS_PER_KG if weight_g else None,
        "duration_s": coerce_number(row.get("duration")),
        "workout_step_index": _whole_number(row.get("wktStepIndex")),
    }
    for field, value in values.items():
        if value is not None and not _strength_accepts(field, value):
            _add_set_issue(issues, ref, field, IssueReason.OUT_OF_RANGE)
            values[field] = None
    category, name = _exercise(row.get("exercises"))
    return ActivityStrengthSet(
        index=index,
        set_type=set_type,
        exercise_category=category,
        exercise_name=name,
        **values,
    )


def _whole_number(value: object) -> int | None:
    number = coerce_number(value)
    if number is None or number % 1:
        return None
    return int(number)


def _exercise(value: object) -> tuple[ExerciseCategory | None, str | None]:
    """Category and code of the most probable exercise of one set."""
    if not isinstance(value, list):
        return None, None
    candidates = [item for item in value if isinstance(item, dict)]
    if not candidates:
        return None, None
    best = max(
        candidates, key=lambda item: coerce_number(item.get("probability")) or 0.0
    )
    category_code = _code(best.get("category"))
    name = _code(best.get("name"))
    if category_code is None:
        return None, name
    try:
        return ExerciseCategory(category_code.lower()), name
    except ValueError:
        return ExerciseCategory.OTHER, name or category_code


def _code(value: object) -> str | None:
    """An upper-case provider code, or None for anything else (free text)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if EXERCISE_NAME_PATTERN.fullmatch(text) else None


def _strength_accepts(name: str, value: object) -> bool:
    """Whether ActivityStrengthSet accepts one value, so its bounds stay in one place."""
    metric: dict[str, Any] = {name: value}
    try:
        ActivityStrengthSet(index=0, set_type=StrengthSetType.ACTIVE, **metric)
    except TypeError, ValueError:
        return False
    return True
