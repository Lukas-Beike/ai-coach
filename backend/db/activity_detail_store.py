"""Persistence of canonical activity detail sets and per-session analysis.

Each provider activity keeps at most one set per detail kind, so several
providers can hold alternative streams, laps, zone times and strength sets for
one canonical session. Functions run inside the caller's unit of work and never commit.
Readers return only details of active records whose session is not deleted;
the rows of tombstoned activities are kept, not destroyed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sys
import zlib
from array import array
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, cast

from backend.canonical.activity_detail import (
    LAP_METRIC_FIELDS,
    MAX_STREAM_POINTS,
    ActivityDetailSet,
    ActivityDfaAlpha1,
    ActivityLap,
    ActivityLapSet,
    ActivitySensor,
    ActivityStreamSet,
    ActivityStrengthSet,
    ActivityStrengthSetSet,
    ZoneBucket,
    ZoneDistribution,
    without_positions,
)
from backend.canonical.records import Provenance
from backend.canonical.sensor_registry import SensorUse
from backend.canonical.vocabulary import (
    POSITION_CHANNELS,
    ActivityDetailKind,
    ActivityDetailOrigin,
    ActivityRecordState,
    ActivitySessionState,
    DfaQuality,
    ExerciseCategory,
    HeartRateSource,
    LapKind,
    LapSource,
    PowerSource,
    ProviderId,
    ProviderRecordState,
    RecordingOrigin,
    SensorRole,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
    StrengthSetSource,
    StrengthSetType,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.canonical_store import WriteOutcome, canonical_json

# Stored blobs are bounded by the schema; decompression never exceeds the
# declared point count, so a corrupt or hostile blob cannot inflate memory.
MAX_CHANNEL_BLOB_BYTES: Final = 4 * 1024 * 1024
_POINT_BYTES: Final = 8
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")

_LAP_METRIC_COLUMNS: Final = LAP_METRIC_FIELDS
_LAP_COLUMNS: Final = (
    "lap_index",
    "kind",
    "start_offset_s",
    "end_offset_s",
    "name",
    *_LAP_METRIC_COLUMNS,
)
_STRENGTH_COLUMNS: Final = (
    "set_index",
    "set_type",
    "exercise_category",
    "exercise_name",
    "reps",
    "weight_kg",
    "duration_s",
    "start_offset_s",
    "workout_step_index",
)
_CHILD_TABLES: Final = (
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_strength_sets",
)
_ZONE_METRIC_BY_KIND: Final = {metric.detail_kind: metric for metric in ZoneMetric}
LOGGER = logging.getLogger("intervals_coach")


@dataclass(frozen=True, slots=True)
class StoredDetailSet:
    """One stored detail set with the bookkeeping that decides re-fetching."""

    provider: str
    provider_activity_id: str
    activity_id: str
    mapper_version: int
    summary_sha256: str | None
    fetched_at: str
    detail: ActivityDetailSet


def encode_series(values: Sequence[float | None]) -> tuple[bytes, int]:
    """Return the zlib-compressed little-endian float64 points and the valid count.

    Gaps are stored as NaN; validated series never contain NaN otherwise.
    """
    points, valid = _pack_series(values)
    return _compress(points), valid


def _compress(points: bytes) -> bytes:
    return zlib.compress(points, 6)


def _pack_series(values: Sequence[float | None]) -> tuple[bytes, int]:
    points = array("d", (math.nan if value is None else value for value in values))
    if sys.byteorder != "little":
        points.byteswap()
    return points.tobytes(), sum(value is not None for value in values)


def decode_series(
    blob: bytes, point_count: int, valid_count: int | None = None
) -> tuple[float | None, ...]:
    """Decode a stored channel; raise ValueError when it does not match its counts."""
    if not 1 <= point_count <= MAX_STREAM_POINTS:
        raise ValueError("point_count is out of range")
    if not isinstance(blob, bytes | bytearray) or len(blob) > MAX_CHANNEL_BLOB_BYTES:
        raise ValueError("stream data is not a bounded blob")
    expected = point_count * _POINT_BYTES
    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(bytes(blob), expected + 1)
    except zlib.error as error:
        raise ValueError("stream data is not valid zlib data") from error
    if (
        len(raw) != expected
        or decompressor.unconsumed_tail
        or decompressor.unused_data
        or not decompressor.eof
    ):
        raise ValueError("stream data does not match its point count")
    points = array("d")
    points.frombytes(raw)
    if sys.byteorder != "little":
        points.byteswap()
    values = tuple(None if math.isnan(value) else value for value in points)
    if valid_count is not None and valid_count != point_count - values.count(None):
        raise ValueError("stream data does not match its valid count")
    return values


GPS_TRACKS_KEY: Final = "gps_tracks_enabled"


def gps_tracks_enabled(db: Any) -> bool:
    """Whether new GPS tracks are stored; on unless the athlete turned it off."""
    row = db.execute("SELECT value FROM kv WHERE key = ?", (GPS_TRACKS_KEY,)).fetchone()
    return row is None or row["value"] != "0"


def stored_track_count(db: Any) -> int:
    """Count the stream sets that hold a stored GPS position."""
    names = sorted(channel.value for channel in POSITION_CHANNELS)
    row = db.execute(
        "SELECT COUNT(DISTINCT provider || char(31) || provider_activity_id) AS total "
        f"FROM activity_stream_channels WHERE channel IN ({', '.join('?' * len(names))})",
        names,
    ).fetchone()
    return int(row["total"])


def delete_stored_tracks(db: Any) -> int:
    """Delete every stored GPS position channel; return the affected stream sets.

    The sets keep their other channels and get the content hash of the
    remaining channels, so later fetches compare against what is stored.
    """
    names = sorted(channel.value for channel in POSITION_CHANNELS)
    marks = ", ".join("?" * len(names))
    keys = [
        (row["provider"], row["provider_activity_id"])
        for row in db.execute(
            "SELECT DISTINCT provider, provider_activity_id FROM activity_stream_channels "
            f"WHERE channel IN ({marks})",
            names,
        )
    ]
    db.execute(
        f"DELETE FROM activity_stream_channels WHERE channel IN ({marks})", names
    )
    for provider, activity_id in keys:
        _rehash_stream_set(db, provider, activity_id)
    return len(keys)


def _rehash_stream_set(db: Any, provider: str, provider_activity_id: str) -> None:
    key = (provider, provider_activity_id, ActivityDetailKind.STREAMS.value)
    header = db.execute(
        "SELECT mapper_version, origin, source_kind, recorded_by, source_record_id, "
        "resolution, hr_source, power_source, sensors, dfa_alpha1 "
        "FROM activity_detail_sets WHERE provider = ? "
        "AND provider_activity_id = ? AND detail_kind = ?",
        key,
    ).fetchone()
    if header is None:
        return
    children: list[tuple[object, ...]] = []
    for row in db.execute(
        "SELECT channel, point_count, valid_count, data FROM activity_stream_channels "
        "WHERE provider = ? AND provider_activity_id = ? ORDER BY channel",
        key[:2],
    ):
        values = decode_series(row["data"], row["point_count"], row["valid_count"])
        points, valid = _pack_series(values)
        children.append((row["channel"], row["point_count"], valid, points))
    content = _content_hash(
        _header_fields(
            detail_kind=key[2],
            mapper_version=header["mapper_version"],
            origin=header["origin"],
            source_kind=header["source_kind"],
            recorded_by=header["recorded_by"],
            source_record_id=header["source_record_id"],
            resolution=header["resolution"],
            lap_source=None,
            zone_boundary_source=None,
            set_source=None,
            hr_source=header["hr_source"],
            power_source=header["power_source"],
            sensors=header["sensors"],
            dfa_alpha1=header["dfa_alpha1"],
        ),
        children,
    )
    db.execute(
        "UPDATE activity_detail_sets SET content_sha256 = ? WHERE provider = ? "
        "AND provider_activity_id = ? AND detail_kind = ?",
        (content, *key),
    )


def _validate_write_inputs(mapper_version: object, summary_sha256: str | None) -> None:
    if isinstance(mapper_version, bool) or not isinstance(mapper_version, int):
        raise TypeError("mapper_version must be an integer")
    if mapper_version < 1:
        raise ValueError("mapper_version must be at least 1")
    if summary_sha256 is not None and not _SHA256_PATTERN.fullmatch(summary_sha256):
        raise ValueError("summary_sha256 must be a lowercase SHA-256 hex digest")


def replace_detail_set(
    db: Any,
    detail: ActivityDetailSet,
    *,
    mapper_version: int,
    summary_sha256: str | None,
    now: str,
) -> WriteOutcome:
    """Store ``detail`` as the provider activity's only set of its kind.

    The provider activity record must exist. Equal content only refreshes the
    fetch bookkeeping and returns UNCHANGED; changed content replaces all rows.
    """
    _validate_write_inputs(mapper_version, summary_sha256)
    if isinstance(detail, ActivityStreamSet) and not gps_tracks_enabled(db):
        stripped = without_positions(detail)
        if stripped is None:
            return WriteOutcome.UNCHANGED
        detail = stripped
    provenance = detail.provenance
    if provenance.provider is None:
        raise ValueError("provenance.provider is required for activity details")
    provider = provenance.provider.value
    key = (provider, detail.provider_activity_id, detail.kind.value)
    header = _header(detail, mapper_version)
    children = _child_rows(detail)
    content_sha256 = _content_hash(header, children)
    fetched_at = (
        provenance.retrieved_at.isoformat()
        if provenance.retrieved_at is not None
        else now
    )
    existing = db.execute(
        "SELECT content_sha256 FROM activity_detail_sets "
        "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
        key,
    ).fetchone()
    if existing is not None and existing["content_sha256"] == content_sha256:
        db.execute(
            "UPDATE activity_detail_sets SET summary_sha256 = ?, fetched_at = ? "
            "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
            (summary_sha256, fetched_at, *key),
        )
        return WriteOutcome.UNCHANGED
    values = (
        header["mapper_version"],
        header["origin"],
        header["source_kind"],
        header["recorded_by"],
        header["source_record_id"],
        header["resolution"],
        header["lap_source"],
        header["zone_boundary_source"],
        header.get("set_source"),
        summary_sha256,
        content_sha256,
        fetched_at,
        header.get("hr_source"),
        header.get("power_source"),
        header.get("sensors"),
        header.get("dfa_alpha1"),
    )
    if existing is None:
        db.execute(
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
            "detail_kind, mapper_version, origin, source_kind, recorded_by, "
            "source_record_id, resolution, lap_source, zone_boundary_source, "
            "set_source, summary_sha256, content_sha256, fetched_at, hr_source, "
            "power_source, sensors, dfa_alpha1, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*key, *values, now, now),
        )
    else:
        _delete_children(db, key)
        db.execute(
            "UPDATE activity_detail_sets SET mapper_version = ?, origin = ?, "
            "source_kind = ?, recorded_by = ?, source_record_id = ?, resolution = ?, "
            "lap_source = ?, zone_boundary_source = ?, set_source = ?, summary_sha256 = ?, "
            "content_sha256 = ?, fetched_at = ?, hr_source = ?, power_source = ?, "
            "sensors = ?, dfa_alpha1 = ?, updated_at = ? "
            "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
            (*values, now, *key),
        )
    _insert_children(db, key, detail, children)
    return WriteOutcome.WRITTEN if existing is None else WriteOutcome.UPDATED


def detail_sets_for(
    db: Any, provider: str, provider_activity_id: str
) -> list[StoredDetailSet]:
    """Return the readable sets of one active provider activity."""
    return _read_sets(
        db,
        "r.provider = ? AND r.provider_activity_id = ?",
        (provider, provider_activity_id),
    )


def detail_sets_for_session(db: Any, activity_id: str) -> list[StoredDetailSet]:
    """Return the readable sets of every provider record bundled in one session.

    Records of sessions merged into ``activity_id`` belong to it as alternatives.
    A deleted session returns nothing.
    """
    return _read_sets(
        db,
        "(s.activity_id = ? OR (s.state = ? AND s.merged_into = ?)) "
        "AND NOT EXISTS (SELECT 1 FROM activity_sessions AS owner "
        "WHERE owner.activity_id = ? AND owner.state = ?)",
        (
            activity_id,
            ActivitySessionState.DUPLICATE.value,
            activity_id,
            activity_id,
            ActivitySessionState.DELETED.value,
        ),
    )


@dataclass(frozen=True, slots=True)
class FullStreamKey:
    """Identity and version of one stored full-resolution stream set."""

    provider: str
    provider_activity_id: str
    content_sha256: str
    summary_sha256: str | None
    # The merge breaks ties between equal sets by the newest fetch.
    fetched_at: str


def strength_sets_for_sessions(
    db: Any,
    activity_ids: Iterable[str],
    *,
    rank: Callable[[StoredDetailSet], Any],
) -> dict[str, StoredDetailSet]:
    """Return the one strength set list per session that ``rank`` puts first.

    Lists of sessions merged into one of ``activity_ids`` belong to that
    survivor. Headers are read in chunks; only the chosen list's sets are read.
    """
    ids = list(
        dict.fromkeys(activity_id for activity_id in activity_ids if activity_id)
    )
    chosen: dict[str, tuple[Any, dict[str, Any], StoredDetailSet]] = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        marks = ", ".join("?" * len(chunk))
        rows = db.execute(
            "SELECT CASE WHEN s.state = ? THEN s.merged_into ELSE s.activity_id END "
            "AS owner, d.provider, d.provider_activity_id, d.detail_kind, "
            "d.mapper_version, d.origin, d.source_kind, d.recorded_by, "
            "d.source_record_id, d.set_source, d.summary_sha256, d.fetched_at, "
            "r.activity_id FROM activity_detail_sets AS d "
            "JOIN activity_records AS r ON r.provider = d.provider "
            "AND r.provider_activity_id = d.provider_activity_id "
            "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
            "WHERE r.state = ? AND s.state <> ? AND d.detail_kind = ? "
            f"AND (s.activity_id IN ({marks}) "
            f"OR (s.state = ? AND s.merged_into IN ({marks})))",
            (
                ActivitySessionState.DUPLICATE.value,
                ActivityRecordState.ACTIVE.value,
                ActivitySessionState.DELETED.value,
                ActivityDetailKind.STRENGTH_SETS.value,
                *chunk,
                ActivitySessionState.DUPLICATE.value,
                *chunk,
            ),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            # The header alone ranks the list; its sets are read only when chosen.
            # An unreadable header skips that list only, like an unreadable set.
            try:
                header = _stored(row, _strength_header(row))
            except (TypeError, ValueError) as error:
                _log_unreadable(row, error)
                continue
            key = rank(header)
            current = chosen.get(row["owner"])
            if current is None or key < current[0]:
                chosen[row["owner"]] = (key, row, header)
    result: dict[str, StoredDetailSet] = {}
    for owner, (_key, row, _header) in chosen.items():
        try:
            detail = _rebuild(db, row)
        except (TypeError, ValueError) as error:
            _log_unreadable(row, error)
            continue
        result[owner] = _stored(row, detail)
    return result


def _strength_header(row: Mapping[str, Any]) -> ActivityStrengthSetSet:
    """A placeholder list with the stored header, for ranking without the sets."""
    return ActivityStrengthSetSet(
        provider_activity_id=row["provider_activity_id"],
        provenance=_provenance(row),
        origin=ActivityDetailOrigin(row["origin"]),
        source=StrengthSetSource(row["set_source"]),
        sets=(ActivityStrengthSet(index=0, set_type=StrengthSetType.ACTIVE),),
    )


def _stored(row: Mapping[str, Any], detail: ActivityDetailSet) -> StoredDetailSet:
    return StoredDetailSet(
        provider=row["provider"],
        provider_activity_id=row["provider_activity_id"],
        activity_id=row["activity_id"],
        mapper_version=row["mapper_version"],
        summary_sha256=row["summary_sha256"],
        fetched_at=row["fetched_at"],
        detail=detail,
    )


def full_stream_keys(
    db: Any, activity_ids: Iterable[str]
) -> dict[str, tuple[FullStreamKey, ...]]:
    """Return the keys of each session's full-resolution stream sets.

    Like ``detail_sets_for_session``, records of sessions merged into a session
    count as its own. Sessions without such a set are absent. No sensor data is
    decoded, so a caller can tell whether a computed curve is still current.
    """
    return _set_keys(
        db,
        activity_ids,
        "d.detail_kind = ? AND d.resolution = ?",
        (ActivityDetailKind.STREAMS.value, StreamResolution.FULL.value),
    )


def lap_set_keys(
    db: Any, activity_ids: Iterable[str]
) -> dict[str, tuple[FullStreamKey, ...]]:
    """Return the keys of each session's lap sets, as ``full_stream_keys`` does."""
    return _set_keys(
        db, activity_ids, "d.detail_kind = ?", (ActivityDetailKind.LAPS.value,)
    )


def analysis_set_keys(
    db: Any, activity_ids: Iterable[str]
) -> dict[str, tuple[FullStreamKey, ...]]:
    """Return the keys of each session's stream and lap sets of any resolution."""
    return _set_keys(
        db,
        activity_ids,
        "d.detail_kind IN (?, ?)",
        (ActivityDetailKind.STREAMS.value, ActivityDetailKind.LAPS.value),
    )


def _set_keys(
    db: Any,
    activity_ids: Iterable[str],
    kind_clause: str,
    kind_values: tuple[str, ...],
) -> dict[str, tuple[FullStreamKey, ...]]:
    ids = list(
        dict.fromkeys(activity_id for activity_id in activity_ids if activity_id)
    )
    keys: dict[str, set[FullStreamKey]] = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        marks = ", ".join("?" * len(chunk))
        rows = db.execute(
            "SELECT CASE WHEN s.state = ? THEN s.merged_into ELSE s.activity_id END "
            "AS owner, d.provider, d.provider_activity_id, d.content_sha256, "
            "d.summary_sha256, d.fetched_at FROM activity_detail_sets AS d "
            "JOIN activity_records AS r ON r.provider = d.provider "
            "AND r.provider_activity_id = d.provider_activity_id "
            "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
            f"WHERE r.state = ? AND s.state <> ? AND {kind_clause} "
            f"AND (s.activity_id IN ({marks}) "
            f"OR (s.state = ? AND s.merged_into IN ({marks})))",
            (
                ActivitySessionState.DUPLICATE.value,
                ActivityRecordState.ACTIVE.value,
                ActivitySessionState.DELETED.value,
                *kind_values,
                *chunk,
                ActivitySessionState.DUPLICATE.value,
                *chunk,
            ),
        ).fetchall()
        for row in rows:
            keys.setdefault(row["owner"], set()).add(
                FullStreamKey(
                    provider=row["provider"],
                    provider_activity_id=row["provider_activity_id"],
                    content_sha256=row["content_sha256"],
                    summary_sha256=row["summary_sha256"],
                    fetched_at=row["fetched_at"],
                )
            )
    return {
        owner: tuple(sorted(values, key=lambda key: key.content_sha256))
        for owner, values in keys.items()
    }


def full_stream_sets_for_session(db: Any, activity_id: str) -> list[StoredDetailSet]:
    """Return only the full-resolution stream sets of ``detail_sets_for_session``."""
    return _read_sets(
        db,
        "d.detail_kind = ? AND d.resolution = ? "
        "AND (s.activity_id = ? OR (s.state = ? AND s.merged_into = ?)) "
        "AND NOT EXISTS (SELECT 1 FROM activity_sessions AS owner "
        "WHERE owner.activity_id = ? AND owner.state = ?)",
        (
            ActivityDetailKind.STREAMS.value,
            StreamResolution.FULL.value,
            activity_id,
            ActivitySessionState.DUPLICATE.value,
            activity_id,
            activity_id,
            ActivitySessionState.DELETED.value,
        ),
    )


def lap_sets_for_session(db: Any, activity_id: str) -> list[StoredDetailSet]:
    """Return only the lap sets of ``detail_sets_for_session``."""
    return _read_sets(
        db,
        "d.detail_kind = ? "
        "AND (s.activity_id = ? OR (s.state = ? AND s.merged_into = ?)) "
        "AND NOT EXISTS (SELECT 1 FROM activity_sessions AS owner "
        "WHERE owner.activity_id = ? AND owner.state = ?)",
        (
            ActivityDetailKind.LAPS.value,
            activity_id,
            ActivitySessionState.DUPLICATE.value,
            activity_id,
            activity_id,
            ActivitySessionState.DELETED.value,
        ),
    )


def strength_record_ids(
    db: Any, provider: str, provider_activity_ids: Collection[str]
) -> set[str]:
    """Return the given provider activity ids whose record is a strength activity."""
    ids = sorted(set(provider_activity_ids))
    if not ids:
        return set()
    return {
        row["provider_activity_id"]
        for row in db.execute(
            "SELECT provider_activity_id FROM activity_records WHERE provider = ? "
            f"AND sport = ? AND provider_activity_id IN ({', '.join('?' for _ in ids)})",
            (provider, Sport.STRENGTH.value, *ids),
        ).fetchall()
    }


def activity_detail_backfill_universe(
    db: Any, provider: str, *, since: datetime
) -> list[str]:
    """Return ids of active records of ``provider`` recorded since ``since``.

    The backfill uses this window universe to prune its empty-marker map.
    """
    return [
        row["provider_activity_id"]
        for row in db.execute(
            "SELECT DISTINCT provider_activity_id FROM activity_records "
            "WHERE provider = ? AND state = ? AND julianday(started_at) >= julianday(?)",
            (provider, ActivityRecordState.ACTIVE.value, since.isoformat()),
        ).fetchall()
    ]


def activity_detail_backfill_candidates(
    db: Any,
    provider: str,
    record_kind: str,
    *,
    since: datetime,
    limit: int,
    mapper_version: int,
    retry_ids: Collection[str] = (),
) -> list[dict[str, str]]:
    """Return recent records whose details are missing or outdated, newest first.

    A record qualifies when it is an active, non-manual record of a live session
    and either has no detail set or only sets whose known summary hash differs
    from the current active raw record. Once one kind was fetched for the current
    summary, kinds Garmin no longer returns do not make the record a candidate
    again, so the backfill does not refetch it on every sync. A set without a
    known hash counts as current. A set stored by an older ``mapper_version`` than
    the one given is outdated, so a mapper change refetches the window.
    ``started_at`` and ``since`` are compared as instants (julianday), so stored
    UTC offsets order correctly. Each row carries the current summary hash,
    which is stored with any fetched details.
    ``retry_ids`` qualify despite current sets, because their last fetch was
    incomplete; the caller bounds how often they are retried.
    """
    retry = sorted(set(retry_ids))
    retry_clause = (
        f" OR r.provider_activity_id IN ({', '.join('?' for _ in retry)})"
        if retry
        else ""
    )
    rows = db.execute(
        "SELECT r.provider_activity_id, r.recorded_by, p.payload_hash AS summary_sha256 "
        "FROM activity_records AS r "
        "JOIN provider_records AS p ON p.provider = r.provider "
        "AND p.record_kind = ? AND p.source_record_id = r.provider_activity_id AND p.state = ? "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id AND s.state <> ? "
        "WHERE r.provider = ? AND r.state = ? AND r.recorded_by <> ? "
        "AND julianday(r.started_at) >= julianday(?) "
        "AND (NOT EXISTS (SELECT 1 FROM activity_detail_sets AS d "
        "WHERE d.provider = r.provider AND d.provider_activity_id = r.provider_activity_id "
        "AND (d.summary_sha256 IS NULL OR d.summary_sha256 = p.payload_hash) "
        "AND d.mapper_version >= ?)"
        + retry_clause
        + ") ORDER BY julianday(r.started_at) DESC, r.provider_activity_id LIMIT ?",
        (
            record_kind,
            ProviderRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            provider,
            ActivityRecordState.ACTIVE.value,
            RecordingOrigin.MANUAL.value,
            since.isoformat(),
            mapper_version,
            *retry,
            limit,
        ),
    ).fetchall()
    return [
        {
            "provider_activity_id": row["provider_activity_id"],
            "recorded_by": row["recorded_by"],
            "summary_sha256": row["summary_sha256"],
        }
        for row in rows
    ]


def sensor_uses(db: Any) -> list[SensorUse]:
    """Return the sensor lists of every live session's stream sets, oldest first.

    Records of one session that name the same sensors are separate entries; the
    registry de-duplicates by sensor key. Rows with an unreadable start or
    sensor list are skipped.
    """
    uses: list[SensorUse] = []
    for row in db.execute(
        "SELECT r.activity_id AS session_id, r.sport, r.started_at, d.sensors "
        "FROM activity_detail_sets AS d "
        "JOIN activity_records AS r ON r.provider = d.provider "
        "AND r.provider_activity_id = d.provider_activity_id "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE d.detail_kind = ? AND d.sensors IS NOT NULL AND r.state = ? "
        "AND s.state <> ? ORDER BY julianday(r.started_at), r.provider_activity_id",
        (
            ActivityDetailKind.STREAMS.value,
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
        ),
    ).fetchall():
        sensors = stored_sensors(row["sensors"])
        try:
            started_at = datetime.fromisoformat(row["started_at"])
        except TypeError, ValueError:
            continue
        if sensors:
            uses.append(SensorUse(row["session_id"], row["sport"], started_at, sensors))
    return uses


@dataclass(frozen=True, slots=True)
class SessionFirstThreshold:
    """The first threshold estimate stored for one session, on its local day."""

    session_id: str
    day: date
    result: ActivityDfaAlpha1


def first_threshold_results(
    db: Any, *, since: date, until: date, sport: Sport
) -> list[SessionFirstThreshold]:
    """Return one stored DFA-a1 estimate per live session of ``sport`` in a day range.

    Records of one session that carry an estimate compete: the better quality
    wins, then the one with more windows. Rows with an unreadable day or estimate
    are skipped. Oldest session first.
    """
    best: dict[str, SessionFirstThreshold] = {}
    for row in db.execute(
        "SELECT CASE WHEN s.state = ? THEN s.merged_into ELSE s.activity_id END "
        "AS session_id, "
        "COALESCE(s.local_date, substr(r.started_at, 1, 10)) AS day, d.dfa_alpha1 "
        "FROM activity_detail_sets AS d "
        "JOIN activity_records AS r ON r.provider = d.provider "
        "AND r.provider_activity_id = d.provider_activity_id "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE d.detail_kind = ? AND d.dfa_alpha1 IS NOT NULL AND r.state = ? "
        "AND s.state <> ? AND r.sport = ? "
        "AND COALESCE(s.local_date, substr(r.started_at, 1, 10)) BETWEEN ? AND ? "
        "ORDER BY day, r.provider_activity_id",
        (
            ActivitySessionState.DUPLICATE.value,
            ActivityDetailKind.STREAMS.value,
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            sport.value,
            since.isoformat(),
            until.isoformat(),
        ),
    ).fetchall():
        result = stored_dfa_alpha1(row["dfa_alpha1"])
        try:
            day = date.fromisoformat(str(row["day"]))
        except ValueError:
            continue
        if result is None:
            continue
        found = best.get(row["session_id"])
        if found is None or _dfa_rank(result) > _dfa_rank(found.result):
            best[row["session_id"]] = SessionFirstThreshold(
                row["session_id"], day, result
            )
    return sorted(best.values(), key=lambda item: (item.day, item.session_id))


def _dfa_rank(result: ActivityDfaAlpha1) -> tuple[int, int]:
    return (1 if result.quality is DfaQuality.GOOD else 0, result.windows)


def stored_strength_source(
    db: Any, provider: str, provider_activity_id: str
) -> str | None:
    """Return the source of the stored strength set list of one provider activity."""
    row = db.execute(
        "SELECT set_source FROM activity_detail_sets WHERE provider = ? "
        "AND provider_activity_id = ? AND detail_kind = ?",
        (provider, provider_activity_id, ActivityDetailKind.STRENGTH_SETS.value),
    ).fetchone()
    return None if row is None else row["set_source"]


def restamp_detail_set(
    db: Any,
    provider: str,
    provider_activity_id: str,
    kind: ActivityDetailKind,
    *,
    summary_sha256: str | None,
    fetched_at: str,
) -> None:
    """Mark a kept set as current for a summary without changing its content."""
    db.execute(
        "UPDATE activity_detail_sets SET summary_sha256 = ?, fetched_at = ? "
        "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
        (summary_sha256, fetched_at, provider, provider_activity_id, kind.value),
    )


def save_analysis(
    db: Any,
    activity_id: str,
    *,
    analysis_version: int,
    input_sha256: str,
    payload: Mapping[str, Any],
    now: str,
) -> WriteOutcome:
    """Store the analysis computed for one session; equal input keeps the row."""
    if isinstance(analysis_version, bool) or not isinstance(analysis_version, int):
        raise TypeError("analysis_version must be an integer")
    if analysis_version < 1:
        raise ValueError("analysis_version must be at least 1")
    if not _SHA256_PATTERN.fullmatch(input_sha256):
        raise ValueError("input_sha256 must be a lowercase SHA-256 hex digest")
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    text = canonical_json(payload)
    existing = db.execute(
        "SELECT analysis_version, input_sha256, payload FROM activity_detail_analysis "
        "WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if existing is not None and (
        existing["analysis_version"],
        existing["input_sha256"],
        existing["payload"],
    ) == (analysis_version, input_sha256, text):
        return WriteOutcome.UNCHANGED
    if existing is None:
        db.execute(
            "INSERT INTO activity_detail_analysis(activity_id, analysis_version, "
            "input_sha256, payload, computed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (activity_id, analysis_version, input_sha256, text, now, now, now),
        )
        return WriteOutcome.WRITTEN
    db.execute(
        "UPDATE activity_detail_analysis SET analysis_version = ?, input_sha256 = ?, "
        "payload = ?, computed_at = ?, updated_at = ? WHERE activity_id = ?",
        (analysis_version, input_sha256, text, now, now, activity_id),
    )
    return WriteOutcome.UPDATED


def analysis_rows_for(
    db: Any, activity_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Return stored analyses of sessions that are not deleted, keyed by session id."""
    ids = list(
        dict.fromkeys(activity_id for activity_id in activity_ids if activity_id)
    )
    rows: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for row in db.execute(
            "SELECT a.activity_id, a.analysis_version, a.input_sha256, a.payload, "
            "a.computed_at FROM activity_detail_analysis AS a "
            "JOIN activity_sessions AS s ON s.activity_id = a.activity_id "
            f"WHERE s.state <> ? AND a.activity_id IN ({', '.join('?' * len(chunk))})",
            (ActivitySessionState.DELETED.value, *chunk),
        ).fetchall():
            rows[row["activity_id"]] = {
                "analysis_version": row["analysis_version"],
                "input_sha256": row["input_sha256"],
                "payload": json.loads(row["payload"]),
                "computed_at": row["computed_at"],
            }
    return rows


def analysis_row_for_record(
    db: Any, provider: str, provider_activity_id: str
) -> dict[str, Any] | None:
    """Return the stored analysis of the session that holds one provider record.

    A session merged into another keeps its analysis row under its own id.
    """
    row = db.execute(
        "SELECT r.activity_id FROM activity_records AS r "
        "JOIN activity_detail_analysis AS a ON a.activity_id = r.activity_id "
        "WHERE r.provider = ? AND r.provider_activity_id = ?",
        (provider, provider_activity_id),
    ).fetchone()
    if row is None:
        return None
    return analysis_rows_for(db, [row["activity_id"]]).get(row["activity_id"])


def stream_export_rows(db: Any) -> Iterable[dict[str, Any]]:
    """Yield every stored stream channel with decoded points for the privacy export.

    Tombstoned activities are included like their records; a channel that no
    longer decodes is exported with ``values`` set to None.
    """
    for row in db.execute(
        "SELECT provider, provider_activity_id, channel, point_count, valid_count, data "
        "FROM activity_stream_channels ORDER BY provider, provider_activity_id, channel"
    ):
        try:
            values: list[float | None] | None = list(
                decode_series(row["data"], row["point_count"], row["valid_count"])
            )
        except ValueError:
            values = None
        yield {
            "provider": row["provider"],
            "provider_activity_id": row["provider_activity_id"],
            "channel": row["channel"],
            "point_count": row["point_count"],
            "valid_count": row["valid_count"],
            "values": values,
        }


def analysis_export_rows(db: Any) -> Iterable[dict[str, Any]]:
    """Yield every stored session analysis with its JSON payload decoded."""
    for row in db.execute(
        "SELECT activity_id, analysis_version, input_sha256, payload, computed_at, "
        "created_at, updated_at FROM activity_detail_analysis ORDER BY activity_id"
    ):
        exported = dict(row)
        exported["payload"] = json.loads(exported["payload"])
        yield exported


def _header(detail: ActivityDetailSet, mapper_version: int) -> dict[str, Any]:
    provenance = detail.provenance
    stream = detail if isinstance(detail, ActivityStreamSet) else None
    return _header_fields(
        detail_kind=detail.kind.value,
        mapper_version=mapper_version,
        origin=detail.origin.value,
        source_kind=provenance.source_kind.value,
        recorded_by=provenance.recorded_by.value,
        source_record_id=provenance.source_record_id,
        resolution=stream.resolution.value if stream else None,
        lap_source=(
            detail.lap_source.value if isinstance(detail, ActivityLapSet) else None
        ),
        zone_boundary_source=(
            detail.boundary_source.value
            if isinstance(detail, ZoneDistribution)
            else None
        ),
        set_source=(
            detail.source.value if isinstance(detail, ActivityStrengthSetSet) else None
        ),
        hr_source=stream.hr_source.value if stream and stream.hr_source else None,
        power_source=(
            stream.power_source.value if stream and stream.power_source else None
        ),
        sensors=(
            json.dumps(
                [_sensor_json(sensor) for sensor in stream.sensors],
                sort_keys=True,
                separators=(",", ":"),
            )
            if stream and stream.sensors
            else None
        ),
        dfa_alpha1=(
            json.dumps(
                _dfa_json(stream.dfa_alpha1), sort_keys=True, separators=(",", ":")
            )
            if stream and stream.dfa_alpha1 is not None
            else None
        ),
    )


def _header_fields(
    *,
    detail_kind: str,
    mapper_version: int,
    origin: str,
    source_kind: str,
    recorded_by: str,
    source_record_id: str | None,
    resolution: str | None,
    lap_source: str | None,
    zone_boundary_source: str | None,
    set_source: str | None,
    hr_source: str | None,
    power_source: str | None,
    sensors: str | None,
    dfa_alpha1: str | None,
) -> dict[str, Any]:
    """The hashed header of a detail set, from values as they are stored.

    The single place that decides which keys are hashed: a write builds it from
    the detail through ``_header`` and a rehash from the stored row, so both
    produce the same content hash for the same set.
    """
    header: dict[str, Any] = {
        "detail_kind": detail_kind,
        "mapper_version": mapper_version,
        "origin": origin,
        "source_kind": source_kind,
        "recorded_by": recorded_by,
        "source_record_id": source_record_id,
        "resolution": resolution,
        "lap_source": lap_source,
        "zone_boundary_source": zone_boundary_source,
    }
    # Only a set that carries a value has its key, so sets without them keep
    # their content hash.
    for key, value in (
        ("set_source", set_source),
        ("hr_source", hr_source),
        ("power_source", power_source),
        ("sensors", sensors),
        ("dfa_alpha1", dfa_alpha1),
    ):
        if value:
            header[key] = value
    return header


def _dfa_json(result: ActivityDfaAlpha1) -> dict[str, Any]:
    return {
        "estimate_bpm": result.estimate_bpm,
        "windows": result.windows,
        "artifact_share": result.artifact_share,
        "quality": result.quality.value,
        "method": result.method,
    }


def stored_dfa_alpha1(text: object) -> ActivityDfaAlpha1 | None:
    """Decode a stored first threshold estimate; an unreadable one yields None."""
    if text is None:
        return None
    try:
        item = json.loads(str(text))
        return ActivityDfaAlpha1(
            estimate_bpm=item["estimate_bpm"],
            windows=item["windows"],
            artifact_share=item["artifact_share"],
            quality=DfaQuality(item["quality"]),
            method=item["method"],
        )
    except TypeError, ValueError, KeyError, AttributeError:
        return None


def _sensor_json(sensor: ActivitySensor) -> dict[str, Any]:
    # ``key`` is a pseudonymous hash of the serial, not the serial itself.
    return {
        "role": sensor.role.value,
        "key": sensor.key,
        "connection": sensor.connection,
        "manufacturer": sensor.manufacturer,
        "product": sensor.product,
    }


def _stored_sensors(text: object) -> tuple[ActivitySensor, ...]:
    if text is None:
        return ()
    return tuple(
        ActivitySensor(
            role=SensorRole(item["role"]),
            key=item["key"],
            connection=item.get("connection"),
            manufacturer=item.get("manufacturer"),
            product=item.get("product"),
        )
        for item in json.loads(str(text))
    )


def stored_sensors(text: object) -> tuple[ActivitySensor, ...]:
    """Decode a stored sensor list; an unreadable list yields no sensors."""
    try:
        return _stored_sensors(text)
    except TypeError, ValueError, KeyError, AttributeError:
        return ()


def _child_rows(detail: ActivityDetailSet) -> list[tuple[object, ...]]:
    if isinstance(detail, ActivityStreamSet):
        rows: list[tuple[object, ...]] = []
        for channel in sorted(detail.channels, key=lambda item: item.value):
            values = detail.channels[channel]
            # Packed, not compressed: the content hash decides whether to write.
            points, valid = _pack_series(values)
            rows.append((channel.value, len(values), valid, points))
        return rows
    if isinstance(detail, ActivityLapSet):
        return [
            (
                lap.index,
                lap.kind.value,
                lap.start_offset_s,
                lap.end_offset_s,
                lap.name,
                *(getattr(lap, column) for column in _LAP_METRIC_COLUMNS),
            )
            for lap in detail.laps
        ]
    if isinstance(detail, ActivityStrengthSetSet):
        return [
            (
                item.index,
                item.set_type.value,
                None
                if item.exercise_category is None
                else item.exercise_category.value,
                item.exercise_name,
                item.reps,
                item.weight_kg,
                item.duration_s,
                item.start_offset_s,
                item.workout_step_index,
            )
            for item in detail.sets
        ]
    return [
        (
            bucket.index,
            float(bucket.seconds),
            _optional_float(bucket.lower),
            _optional_float(bucket.upper),
            bucket.label,
        )
        for bucket in detail.buckets
    ]


def _content_hash(header: Mapping[str, Any], children: list[tuple[object, ...]]) -> str:
    digest = hashlib.sha256(canonical_json(header).encode("utf-8"))
    for row in children:
        for value in row:
            if isinstance(value, bytes):
                # Hash the packed points, not zlib output, which may vary by library.
                digest.update(value)
            else:
                digest.update(json.dumps(value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\x1e")
    return digest.hexdigest()


def _delete_children(db: Any, key: tuple[str, str, str]) -> None:
    for table in _CHILD_TABLES:
        db.execute(
            f"DELETE FROM {table} WHERE provider = ? AND provider_activity_id = ? "
            "AND detail_kind = ?",
            key,
        )


def _insert_children(
    db: Any,
    key: tuple[str, str, str],
    detail: ActivityDetailSet,
    rows: list[tuple[object, ...]],
) -> None:
    if isinstance(detail, ActivityStreamSet):
        db.executemany(
            "INSERT INTO activity_stream_channels(provider, provider_activity_id, "
            "detail_kind, channel, point_count, valid_count, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (*key, channel, count, valid, _compress(cast(bytes, points)))
                for channel, count, valid, points in rows
            ],
        )
    elif isinstance(detail, ActivityLapSet):
        db.executemany(
            "INSERT INTO activity_laps(provider, provider_activity_id, detail_kind, "
            f"{', '.join(_LAP_COLUMNS)}) "
            f"VALUES ({', '.join('?' * (3 + len(_LAP_COLUMNS)))})",
            [(*key, *row) for row in rows],
        )
    elif isinstance(detail, ActivityStrengthSetSet):
        db.executemany(
            "INSERT INTO activity_strength_sets(provider, provider_activity_id, "
            f"detail_kind, {', '.join(_STRENGTH_COLUMNS)}) "
            f"VALUES ({', '.join('?' * (3 + len(_STRENGTH_COLUMNS)))})",
            [(*key, *row) for row in rows],
        )
    else:
        db.executemany(
            "INSERT INTO activity_zone_times(provider, provider_activity_id, "
            "detail_kind, zone_index, seconds, lower_bound, upper_bound, label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*key, *row) for row in rows],
        )


def _read_sets(
    db: Any, where: str, params: tuple[object, ...]
) -> list[StoredDetailSet]:
    """Rebuild typed sets; a set that no longer validates is skipped, not raised."""
    cursor = db.execute(
        "SELECT d.provider, d.provider_activity_id, d.detail_kind, d.mapper_version, "
        "d.origin, d.source_kind, d.recorded_by, d.source_record_id, d.resolution, "
        "d.lap_source, d.zone_boundary_source, d.set_source, d.summary_sha256, "
        "d.fetched_at, d.hr_source, d.power_source, d.sensors, d.dfa_alpha1, "
        "r.activity_id FROM activity_detail_sets AS d "
        "JOIN activity_records AS r ON r.provider = d.provider "
        "AND r.provider_activity_id = d.provider_activity_id "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE r.state = ? AND s.state <> ? AND {where} "
        "ORDER BY d.provider, d.provider_activity_id, d.detail_kind",
        (
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            *params,
        ),
    )
    stored: list[StoredDetailSet] = []
    for raw in cursor.fetchall():
        row = dict(raw)
        try:
            detail = _rebuild(db, row)
        except (TypeError, ValueError) as error:
            _log_unreadable(row, error)
            continue
        stored.append(_stored(row, detail))
    return stored


def _log_unreadable(row: Mapping[str, Any], error: Exception) -> None:
    # One unreadable set must not hide the others; report it without stored
    # values or error text so the corruption stays visible.
    LOGGER.warning(
        "Stored activity detail set is unreadable",
        extra={
            "event": "activity_detail_unreadable",
            "context": {
                "provider": row["provider"],
                "detail_kind": row["detail_kind"],
                "error": type(error).__name__,
            },
        },
    )


def _provenance(row: Mapping[str, Any]) -> Provenance:
    return Provenance(
        provider=ProviderId(row["provider"]),
        source_kind=SourceKind(row["source_kind"]),
        source_record_id=row["source_record_id"],
        recorded_by=RecordingOrigin(row["recorded_by"]),
        retrieved_at=_aware_datetime(row["fetched_at"]),
        label=None,
    )


def _rebuild(db: Any, row: Mapping[str, Any]) -> ActivityDetailSet:
    key = (row["provider"], row["provider_activity_id"], row["detail_kind"])
    kind = ActivityDetailKind(row["detail_kind"])
    common = {
        "provider_activity_id": row["provider_activity_id"],
        "provenance": _provenance(row),
        "origin": ActivityDetailOrigin(row["origin"]),
    }
    if kind is ActivityDetailKind.STREAMS:
        channels = {
            StreamChannel(channel["channel"]): decode_series(
                channel["data"], channel["point_count"], channel["valid_count"]
            )
            for channel in db.execute(
                "SELECT channel, point_count, valid_count, data FROM activity_stream_channels "
                "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
                key,
            ).fetchall()
        }
        return ActivityStreamSet(
            **common,
            resolution=StreamResolution(row["resolution"]),
            channels=channels,
            hr_source=(
                None if row["hr_source"] is None else HeartRateSource(row["hr_source"])
            ),
            power_source=(
                None
                if row["power_source"] is None
                else PowerSource(row["power_source"])
            ),
            # Optional metadata must never make the stream set unreadable.
            sensors=stored_sensors(row["sensors"]),
            dfa_alpha1=stored_dfa_alpha1(row["dfa_alpha1"]),
        )
    if kind is ActivityDetailKind.LAPS:
        laps = tuple(
            ActivityLap(
                index=lap["lap_index"],
                kind=LapKind(lap["kind"]),
                start_offset_s=lap["start_offset_s"],
                end_offset_s=lap["end_offset_s"],
                name=lap["name"],
                **{column: lap[column] for column in _LAP_METRIC_COLUMNS},
            )
            for lap in db.execute(
                f"SELECT {', '.join(_LAP_COLUMNS)} FROM activity_laps "
                "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ? "
                "ORDER BY lap_index",
                key,
            ).fetchall()
        )
        return ActivityLapSet(
            **common, lap_source=LapSource(row["lap_source"]), laps=laps
        )
    if kind is ActivityDetailKind.STRENGTH_SETS:
        return ActivityStrengthSetSet(
            **common,
            source=StrengthSetSource(row["set_source"]),
            sets=tuple(
                _strength_set(item)
                for item in db.execute(
                    f"SELECT {', '.join(_STRENGTH_COLUMNS)} FROM activity_strength_sets "
                    "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ? "
                    "ORDER BY set_index",
                    key,
                ).fetchall()
            ),
        )
    buckets = tuple(
        ZoneBucket(
            index=bucket["zone_index"],
            seconds=bucket["seconds"],
            lower=bucket["lower_bound"],
            upper=bucket["upper_bound"],
            label=bucket["label"],
        )
        for bucket in db.execute(
            "SELECT zone_index, seconds, lower_bound, upper_bound, label "
            "FROM activity_zone_times WHERE provider = ? AND provider_activity_id = ? "
            "AND detail_kind = ? ORDER BY zone_index",
            key,
        ).fetchall()
    )
    return ZoneDistribution(
        **common,
        metric=_ZONE_METRIC_BY_KIND[kind],
        boundary_source=ZoneBoundarySource(row["zone_boundary_source"]),
        buckets=buckets,
    )


def _strength_set(row: Mapping[str, Any]) -> ActivityStrengthSet:
    category = row["exercise_category"]
    return ActivityStrengthSet(
        index=row["set_index"],
        set_type=StrengthSetType(row["set_type"]),
        exercise_category=None if category is None else ExerciseCategory(category),
        exercise_name=row["exercise_name"],
        reps=row["reps"],
        weight_kg=row["weight_kg"],
        duration_s=row["duration_s"],
        start_offset_s=row["start_offset_s"],
        workout_step_index=row["workout_step_index"],
    )


def _aware_datetime(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]
