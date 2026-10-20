"""Canonical writes of Intervals activity details and session analysis.

One owner for both ingest paths: a fresh load of ``GET /activity/{id}`` and a
backfill of one kv record written by an earlier release. The writer is stateless
and never opens a transaction; the caller passes the connection of its unit of
work, so the kv record and the canonical rows commit or roll back together.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from backend.canonical.activity_detail import ActivityDetailSet
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ActivityRecordState,
    ProviderId,
    RecordingOrigin,
)
from backend.db.activity_detail_store import (
    detail_origins,
    remove_detail_sets,
    replace_detail_set,
    save_analysis,
)
from backend.db.canonical_store import (
    WriteOutcome,
    activity_record_link,
    canonical_json,
)
from backend.providers.intervals_activity_detail_mapping import (
    MAPPER_VERSION,
    map_intervals_activity_detail,
    map_legacy_activity_detail,
)

# Version 1: session analysis stored as target snapshot, analysis and calendar profile.
ACTIVITY_DETAIL_ANALYSIS_VERSION: Final = 1
_ANALYSIS_KEYS: Final = ("target_snapshot", "session_analysis", "calendar_profile")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_INTERVALS: Final = ProviderId.INTERVALS.value


class DetailWriteOutcome(StrEnum):
    WRITTEN = "written"
    UNCHANGED = "unchanged"
    # No active Intervals activity record exists for the id; nothing is written.
    NO_RECORD = "no_record"
    # The document holds neither a mappable detail set nor an analysis payload.
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DetailWriteResult:
    """Outcome of one write, plus the number of mapping issues it produced."""

    outcome: DetailWriteOutcome
    issues: int = 0


class CanonicalDetailWriter:
    """Write mapped detail sets and session analysis inside the caller's transaction."""

    def write_fetch(
        self,
        db: Any,
        *,
        activity_id: str,
        detail: object,
        streams: object,
        record: Mapping[str, Any],
        now: str,
    ) -> DetailWriteResult:
        """Store a fresh load; it replaces every detail kind of the activity."""
        link = activity_record_link(db, _INTERVALS, activity_id)
        if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
            return DetailWriteResult(DetailWriteOutcome.NO_RECORD)
        result = map_intervals_activity_detail(
            detail,
            streams,
            recorded_by=_recorded_by(link["recorded_by"]),
            retrieved_at=_aware_time(record.get("observed_at")),
        )
        if not result.records and not _has_analysis_payload(record):
            # Nothing usable arrived: keep the stored sets instead of erasing them.
            return DetailWriteResult(DetailWriteOutcome.INVALID, len(result.issues))
        outcomes = _write_sets(
            db, result.records, _sha256_or_none(record.get("summary_sha256")), now
        )
        # A fresh fetch is authoritative for the whole Intervals activity.
        remove_detail_sets(
            db,
            _INTERVALS,
            activity_id,
            keep={item.kind for item in result.records},
        )
        analysis = _write_analysis(db, link, record, now)
        if analysis is not None:
            outcomes.append(analysis)
        return _result(outcomes, len(result.issues))

    def write_legacy(self, db: Any, *, record: object, now: str) -> DetailWriteResult:
        """Backfill one stored kv record; sets from a fresh load in canonical win."""
        if not isinstance(record, dict):
            return DetailWriteResult(DetailWriteOutcome.INVALID)
        activity_id = record.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id:
            return DetailWriteResult(DetailWriteOutcome.INVALID)
        link = activity_record_link(db, _INTERVALS, activity_id)
        if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
            return DetailWriteResult(DetailWriteOutcome.NO_RECORD)
        if ActivityDetailOrigin.FETCH.value in detail_origins(
            db, _INTERVALS, activity_id
        ):
            return DetailWriteResult(DetailWriteOutcome.UNCHANGED)
        result = map_legacy_activity_detail(
            record, recorded_by=_recorded_by(link["recorded_by"])
        )
        if not result.records and not _has_analysis_payload(record):
            return DetailWriteResult(DetailWriteOutcome.INVALID, len(result.issues))
        outcomes = _write_sets(
            db, result.records, _sha256_or_none(record.get("summary_sha256")), now
        )
        analysis = _write_analysis(db, link, record, now)
        if analysis is not None:
            outcomes.append(analysis)
        return _result(outcomes, len(result.issues))


def _recorded_by(value: object) -> RecordingOrigin:
    if not isinstance(value, str):
        return RecordingOrigin.UNKNOWN
    try:
        return RecordingOrigin(value)
    except ValueError:
        return RecordingOrigin.UNKNOWN


def _aware_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.utcoffset() is not None:
            return parsed
    raise ValueError("observed_at must be an ISO timestamp with an offset")


def _sha256_or_none(value: object) -> str | None:
    if isinstance(value, str) and _SHA256_PATTERN.fullmatch(value):
        return value
    return None


def _has_analysis_payload(record: Mapping[str, Any]) -> bool:
    return any(record.get(key) is not None for key in _ANALYSIS_KEYS)


def _write_sets(
    db: Any,
    sets: tuple[ActivityDetailSet, ...],
    summary_sha256: str | None,
    now: str,
) -> list[WriteOutcome]:
    return [
        replace_detail_set(
            db,
            item,
            mapper_version=MAPPER_VERSION,
            summary_sha256=summary_sha256,
            now=now,
        )
        for item in sets
    ]


def _write_analysis(
    db: Any,
    link: Mapping[str, Any],
    record: Mapping[str, Any],
    now: str,
) -> WriteOutcome | None:
    """Store the session analysis; only sessions with a local id have one."""
    activity_id = link["activity_id"]
    if activity_id is None or not _has_analysis_payload(record):
        return None
    payload = {key: record.get(key) for key in _ANALYSIS_KEYS}
    return save_analysis(
        db,
        activity_id,
        analysis_version=ACTIVITY_DETAIL_ANALYSIS_VERSION,
        input_sha256=_analysis_input_hash(record),
        payload=payload,
        now=now,
    )


def _analysis_input_hash(record: Mapping[str, Any]) -> str:
    stored = _sha256_or_none(record.get("content_sha256"))
    if stored is not None:
        return stored
    activity = record.get("activity")
    text = canonical_json(activity if isinstance(activity, Mapping) else {})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _result(outcomes: list[WriteOutcome], issues: int) -> DetailWriteResult:
    written = any(
        outcome in (WriteOutcome.WRITTEN, WriteOutcome.UPDATED) for outcome in outcomes
    )
    outcome = DetailWriteOutcome.WRITTEN if written else DetailWriteOutcome.UNCHANGED
    return DetailWriteResult(outcome, issues)
