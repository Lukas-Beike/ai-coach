"""Delete stored activity detail records once the canonical tables prove them, once.

The retirement runs after the detail backfill has completed. It reads each
``activity_detail:<sha>`` kv record in key order and deletes it only when every
detail set, lap, zone bucket and analysis value it holds is present in the
canonical tables; any other record stays unchanged and counts its first failing
check. Before the laps are compared, lap metrics that the canonical lap set lacks
are copied from the record, so older lap sets gain values such as the maximum
speed. Each batch commits its deletions, refills and cursor in one writer
transaction, so a failed batch rolls back and the next run resumes from the last
committed key. Failure notes and the prefetch floor are other keys and are never
touched. A change of the retirement or mapper version starts the pass again.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from backend.activities.detail_store import ActivityDetailStore
from backend.canonical.activity_detail import (
    LAP_METRIC_FIELDS,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneDistribution,
)
from backend.canonical.legacy_planning_fields import normalize_legacy_detail_targets
from backend.canonical.vocabulary import (
    ActivityRecordState,
    LapKind,
    ProviderId,
    StreamResolution,
)
from backend.db.activity_detail_store import (
    analysis_row_for_record,
    detail_sets_for,
    refill_lap_metrics,
)
from backend.db.canonical_store import activity_record_link, canonical_json
from backend.db.repositories import KeyValueRepository
from backend.providers.intervals_activity_detail_mapping import (
    MAPPER_VERSION,
    STREAM_KEY_CHANNELS,
    map_legacy_activity_detail,
)
from backend.providers.intervals_activity_detail_projection import _downsample_series
from backend.sync.activity_detail_canonical import recording_origin
from backend.sync.canonical_backfill import BackfillStatus, BatchReport

STATE_KEY: Final = "activity_detail_retirement_state"
RETIREMENT_VERSION: Final = 1
DEFAULT_BATCH_SIZE: Final = 20
MIN_BATCH_SIZE: Final = 1
MAX_BATCH_SIZE: Final = 100
STAGE: Final = "activity_detail_retirement"
RETIRED: Final = "retired"
LAPS_REFILLED: Final = "laps_refilled"
# Each kept record counts the first check it fails, in this order.
_REASONS: Final = (
    "invalid",
    "no_record",
    "mapping_issues",
    "unmapped_stream",
    "no_canonical",
    "fingerprint_mismatch",
    "streams_unproven",
    "laps_mismatch",
    "zones_mismatch",
    "analysis_mismatch",
)
_COUNTER_NAMES: Final = (RETIRED, *_REASONS, LAPS_REFILLED)
_ANALYSIS_KEYS: Final = ("target_snapshot", "session_analysis", "calendar_profile")
_INTERVALS: Final = ProviderId.INTERVALS.value


def _empty_counters() -> dict[str, int]:
    return dict.fromkeys(_COUNTER_NAMES, 0)


def _fresh_state() -> dict[str, Any]:
    return {
        "status": BackfillStatus.PENDING.value,
        "retirement_version": None,
        "mapper_version": None,
        "cursor": "",
        "batches": 0,
        "counters": _empty_counters(),
        "completed_at": None,
    }


def _is_well_formed(state: object) -> bool:
    return (
        isinstance(state, dict)
        and isinstance(state.get("status"), str)
        and isinstance(state.get("cursor"), str)
        and isinstance(state.get("counters"), dict)
        and isinstance(state.get("batches"), int)
    )


class ActivityDetailRetirement:
    """Retires proven detail records one batch at a time. The caller owns the transaction."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        clock: Callable[[], str],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}"
            )
        self._key_values = key_values
        self._clock = clock
        self._batch_size = batch_size

    @property
    def stage(self) -> str:
        return STAGE

    def run_batch(self, db: Any) -> BatchReport:
        """Check one batch, delete its proven records and write the cursor."""
        state = self._load(db)
        if (
            state.get("retirement_version") != RETIREMENT_VERSION
            or state.get("mapper_version") != MAPPER_VERSION
        ):
            state.update(
                retirement_version=RETIREMENT_VERSION,
                mapper_version=MAPPER_VERSION,
                cursor="",
                batches=0,
                counters=_empty_counters(),
                completed_at=None,
            )
        elif state["status"] == BackfillStatus.COMPLETE.value:
            return BatchReport(items=0, done=True)
        rows = ActivityDetailStore.records_after(db, state["cursor"], self._batch_size)
        now = self._clock()
        counters = state["counters"]
        for key, record in rows:
            outcome, refilled = _retire(db, record, now)
            if outcome == RETIRED:
                # The cursor is the last key seen, so deleting it keeps the order.
                self._key_values.delete(db, key)
            counters[outcome] += 1
            counters[LAPS_REFILLED] += refilled
            state["cursor"] = key
        done = len(rows) < self._batch_size
        state["status"] = (
            BackfillStatus.COMPLETE if done else BackfillStatus.RUNNING
        ).value
        state["completed_at"] = now if done else None
        state["batches"] += 1
        self._save(db, state)
        return BatchReport(items=len(rows), done=done)

    def mark_failed(self, db: Any) -> None:
        """Record that the run stopped; the cursor stays at the last committed batch."""
        state = self._load(db)
        state["status"] = BackfillStatus.FAILED.value
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return content-free status, batch count and counters of the current pass."""
        state = self._load(db)
        return {
            "status": state["status"],
            "batches": state["batches"],
            "counters": state["counters"],
        }

    def _load(self, db: Any) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return _fresh_state()
        try:
            state = json.loads(raw)
        except ValueError:
            return _fresh_state()
        if not _is_well_formed(state):
            return _fresh_state()
        state["counters"] = {**_empty_counters(), **state["counters"]}
        return state

    def _save(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def _retire(db: Any, record: object, now: str) -> tuple[str, int]:
    """Return the outcome for one record and the number of lap sets refilled."""
    if not isinstance(record, dict):
        return "invalid", 0
    activity_id = record.get("activity_id")
    if not isinstance(activity_id, str) or not activity_id:
        return "invalid", 0
    link = activity_record_link(db, _INTERVALS, activity_id)
    if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
        return "no_record", 0
    mapped = map_legacy_activity_detail(
        record, recorded_by=recording_origin(link["recorded_by"])
    )
    if mapped.issues:
        return "mapping_issues", 0
    if not _streams_mappable(record):
        return "unmapped_stream", 0
    outcome, pairs = _paired_sets(db, record, activity_id, mapped.records)
    if outcome is not None:
        return outcome, 0
    outcome, refilled = _check_laps(db, activity_id, pairs, now)
    if outcome is not None:
        return outcome, refilled
    if any(
        isinstance(legacy, ZoneDistribution) and not _zones_equal(legacy, canonical)
        for legacy, canonical in pairs
    ):
        return "zones_mismatch", refilled
    if not _analysis_proven(db, activity_id, record, compared=bool(pairs)):
        return "analysis_mismatch", refilled
    return RETIRED, refilled


def _paired_sets(
    db: Any, record: dict[str, Any], activity_id: str, legacy_sets: Sequence[Any]
) -> tuple[str | None, list[tuple[Any, Any]]]:
    """Pair each legacy set with its canonical set, or name why they cannot pair."""
    stored = {
        item.detail.kind: item for item in detail_sets_for(db, _INTERVALS, activity_id)
    }
    pairs: list[tuple[Any, Any]] = []
    for legacy in legacy_sets:
        current = stored.get(legacy.kind)
        if current is None:
            return "no_canonical", []
        if current.summary_sha256 != record.get("summary_sha256"):
            return "fingerprint_mismatch", []
        pairs.append((legacy, current.detail))
    for legacy, canonical in pairs:
        if isinstance(legacy, ActivityStreamSet) and not _streams_proven(
            legacy, canonical
        ):
            return "streams_unproven", []
    return None, pairs


def _check_laps(
    db: Any, activity_id: str, pairs: list[tuple[Any, Any]], now: str
) -> tuple[str | None, int]:
    """Refill missing lap metrics, then compare the laps; return the outcome and refills."""
    refilled = 0
    for legacy, canonical in pairs:
        if not isinstance(legacy, ActivityLapSet):
            continue
        if not isinstance(canonical, ActivityLapSet) or not _laps_aligned(
            legacy.laps, canonical.laps
        ):
            return "laps_mismatch", 0
        missing = _missing_metrics(legacy.laps, canonical.laps)
        if missing and refill_lap_metrics(
            db, _INTERVALS, activity_id, missing, now=now
        ):
            refilled = 1
        if not _laps_equal(legacy.laps, canonical.laps):
            return "laps_mismatch", refilled
    return None, refilled


def _streams_mappable(record: Mapping[str, Any]) -> bool:
    """Whether every stored stream key maps to its own canonical channel.

    A second alias of a channel would be dropped by the mapper, so its values
    would be lost by deleting the record.
    """
    activity = record.get("activity")
    streams = activity.get("streams") if isinstance(activity, dict) else None
    if not isinstance(streams, dict):
        return True
    channels = [STREAM_KEY_CHANNELS.get(key) for key in streams]
    return None not in channels and len(set(channels)) == len(channels)


def _streams_proven(legacy: ActivityStreamSet, canonical: ActivityDetailSet) -> bool:
    if not isinstance(canonical, ActivityStreamSet):
        return False
    if set(legacy.channels) != set(canonical.channels):
        return False
    if legacy.resolution is canonical.resolution:
        return all(
            canonical.channels[channel] == values
            for channel, values in legacy.channels.items()
        )
    if (
        legacy.resolution is StreamResolution.DOWNSAMPLED
        and canonical.resolution is StreamResolution.FULL
    ):
        # An earlier release stored the projection's downsampled series.
        return all(
            tuple(_downsample_series(list(canonical.channels[channel]))) == values
            for channel, values in legacy.channels.items()
        )
    return False


def _laps_aligned(
    legacy: tuple[ActivityLap, ...], canonical: tuple[ActivityLap, ...]
) -> bool:
    """Whether each legacy lap has the canonical lap of the same position and kind.

    Canonical may hold more laps, because stored records keep at most 200. Stored
    records never carry the interval type, so their laps map to LAP.
    """
    return len(canonical) >= len(legacy) and all(
        (old.index, old.start_offset_s, old.end_offset_s)
        == (new.index, new.start_offset_s, new.end_offset_s)
        and (old.kind is LapKind.LAP or old.kind is new.kind)
        for old, new in zip(legacy, canonical, strict=False)
    )


def _missing_metrics(
    legacy: tuple[ActivityLap, ...], canonical: tuple[ActivityLap, ...]
) -> dict[int, dict[str, float]]:
    missing: dict[int, dict[str, float]] = {}
    for old, new in zip(legacy, canonical, strict=False):
        values = {
            name: getattr(old, name)
            for name in LAP_METRIC_FIELDS
            if getattr(old, name) is not None and getattr(new, name) is None
        }
        if values:
            missing[new.index] = values
    return missing


def _laps_equal(
    legacy: tuple[ActivityLap, ...], canonical: tuple[ActivityLap, ...]
) -> bool:
    """Compare names and metrics; a metric missing canonically was just refilled."""
    for old, new in zip(legacy, canonical, strict=False):
        if old.name != new.name and not (
            old.name is not None
            and new.name is not None
            and len(old.name) == 120
            and new.name.startswith(old.name)
        ):
            return False
        for name in LAP_METRIC_FIELDS:
            value = getattr(old, name)
            stored = getattr(new, name)
            if value is not None and stored is not None and stored != value:
                return False
    return True


def _zones_equal(legacy: ZoneDistribution, canonical: ActivityDetailSet) -> bool:
    if not isinstance(canonical, ZoneDistribution):
        return False

    def buckets(item: ZoneDistribution) -> list[tuple[object, ...]]:
        return [
            (bucket.index, bucket.seconds, bucket.lower, bucket.upper, bucket.label)
            for bucket in item.buckets
        ]

    return buckets(legacy) == buckets(canonical)


def _analysis_proven(
    db: Any, activity_id: str, record: Mapping[str, Any], *, compared: bool
) -> bool:
    """Whether the stored session analysis holds the record's analysis values.

    A record without compared detail sets is proven only by an existing payload.
    """
    row = analysis_row_for_record(db, _INTERVALS, activity_id)
    if row is None:
        has_analysis = any(record.get(key) is not None for key in _ANALYSIS_KEYS)
        return compared and not has_analysis
    payload = row["payload"]
    if not isinstance(payload, dict):
        return False
    if payload.get("summary_sha256") != record.get("summary_sha256"):
        return False
    try:
        record = normalize_legacy_detail_targets(record)
    except RuntimeError:
        return False
    return all(
        canonical_json({key: payload.get(key)})
        == canonical_json({key: record.get(key)})
        for key in _ANALYSIS_KEYS
    )
