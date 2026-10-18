"""Persistence of canonical activity detail sets and per-session analysis.

Each provider activity keeps at most one set per detail kind, so several
providers can hold alternative streams, laps and zone times for one canonical
session. Functions run inside the caller's unit of work and never commit.
Readers return only details of active records whose session is not deleted;
the rows of tombstoned activities are kept, not destroyed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import zlib
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from backend.canonical.activity_detail import (
    MAX_STREAM_POINTS,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityDetailOrigin,
    ActivityRecordState,
    ActivitySessionState,
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
from backend.db.canonical_store import WriteOutcome, canonical_json

# Stored blobs are bounded by the schema; decompression never exceeds the
# declared point count, so a corrupt or hostile blob cannot inflate memory.
MAX_CHANNEL_BLOB_BYTES: Final = 4 * 1024 * 1024
_POINT_BYTES: Final = 8
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")

_LAP_METRIC_COLUMNS: Final = (
    "moving_duration_s",
    "distance_m",
    "avg_hr",
    "max_hr",
    "avg_power",
    "max_power",
    "normalized_power",
    "avg_cadence",
    "avg_speed_mps",
    "elevation_gain_m",
    "load",
    "intensity_pct",
)
_LAP_COLUMNS: Final = (
    "lap_index",
    "kind",
    "start_offset_s",
    "end_offset_s",
    "name",
    *_LAP_METRIC_COLUMNS,
)
_ZONE_METRIC_BY_KIND: Final = {metric.detail_kind: metric for metric in ZoneMetric}


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
    return zlib.compress(points, 6), valid


def _pack_series(values: Sequence[float | None]) -> tuple[bytes, int]:
    points = array("d", (math.nan if value is None else value for value in values))
    if sys.byteorder != "little":
        points.byteswap()
    return points.tobytes(), sum(value is not None for value in values)


def decode_series(blob: bytes, point_count: int) -> tuple[float | None, ...]:
    """Decode a stored channel; raise ValueError when it does not match its count."""
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
    return tuple(None if math.isnan(value) else value for value in points)


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
    if isinstance(mapper_version, bool) or not isinstance(mapper_version, int):
        raise TypeError("mapper_version must be an integer")
    if mapper_version < 1:
        raise ValueError("mapper_version must be at least 1")
    if summary_sha256 is not None and not _SHA256_PATTERN.fullmatch(summary_sha256):
        raise ValueError("summary_sha256 must be a lowercase SHA-256 hex digest")
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
        summary_sha256,
        content_sha256,
        fetched_at,
    )
    if existing is None:
        db.execute(
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
            "detail_kind, mapper_version, origin, source_kind, recorded_by, "
            "source_record_id, resolution, lap_source, zone_boundary_source, "
            "summary_sha256, content_sha256, fetched_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*key, *values, now, now),
        )
    else:
        _delete_children(db, key)
        db.execute(
            "UPDATE activity_detail_sets SET mapper_version = ?, origin = ?, "
            "source_kind = ?, recorded_by = ?, source_record_id = ?, resolution = ?, "
            "lap_source = ?, zone_boundary_source = ?, summary_sha256 = ?, "
            "content_sha256 = ?, fetched_at = ?, updated_at = ? "
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
    ids = list(dict.fromkeys(activity_id for activity_id in activity_ids if activity_id))
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
                decode_series(row["data"], row["point_count"])
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
    return {
        "detail_kind": detail.kind.value,
        "mapper_version": mapper_version,
        "origin": detail.origin.value,
        "source_kind": provenance.source_kind.value,
        "recorded_by": provenance.recorded_by.value,
        "source_record_id": provenance.source_record_id,
        "resolution": (
            detail.resolution.value if isinstance(detail, ActivityStreamSet) else None
        ),
        "lap_source": (
            detail.lap_source.value if isinstance(detail, ActivityLapSet) else None
        ),
        "zone_boundary_source": (
            detail.boundary_source.value
            if isinstance(detail, ZoneDistribution)
            else None
        ),
    }


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
    for table in ("activity_stream_channels", "activity_laps", "activity_zone_times"):
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
                (*key, channel, count, valid, zlib.compress(points, 6))
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
        "d.lap_source, d.zone_boundary_source, d.summary_sha256, d.fetched_at, "
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
        except (TypeError, ValueError):
            continue
        stored.append(
            StoredDetailSet(
                provider=row["provider"],
                provider_activity_id=row["provider_activity_id"],
                activity_id=row["activity_id"],
                mapper_version=row["mapper_version"],
                summary_sha256=row["summary_sha256"],
                fetched_at=row["fetched_at"],
                detail=detail,
            )
        )
    return stored


def _rebuild(db: Any, row: Mapping[str, Any]) -> ActivityDetailSet:
    key = (row["provider"], row["provider_activity_id"], row["detail_kind"])
    kind = ActivityDetailKind(row["detail_kind"])
    common = {
        "provider_activity_id": row["provider_activity_id"],
        "provenance": Provenance(
            provider=ProviderId(row["provider"]),
            source_kind=SourceKind(row["source_kind"]),
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            retrieved_at=_aware_datetime(row["fetched_at"]),
            label=None,
        ),
        "origin": ActivityDetailOrigin(row["origin"]),
    }
    if kind is ActivityDetailKind.STREAMS:
        channels = {
            StreamChannel(channel["channel"]): decode_series(
                channel["data"], channel["point_count"]
            )
            for channel in db.execute(
                "SELECT channel, point_count, data FROM activity_stream_channels "
                "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
                key,
            ).fetchall()
        }
        return ActivityStreamSet(
            **common,
            resolution=StreamResolution(row["resolution"]),
            channels=channels,
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
