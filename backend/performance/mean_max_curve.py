"""Per-session mean-maximal curves from canonical full-resolution streams.

Only stream sets stored at full resolution are read: a downsampled set never
enters a best value. A set whose provider summary changed since it was fetched is
stale and left out, as the activity detail withholds its analysis. A session
counts once, with the streams of every record bundled in it merged as in the
activity detail. Curves are computed at read time and kept in memory under a
fingerprint of the method, the session's records and the content hashes of its
stream sets, so any source change or new method version recomputes them.
Nothing is persisted; reads never touch a provider.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.activities.detail_contract import measured_order
from backend.activities.detail_merge import merge_details
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ProviderId
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import FullStreamKey
from backend.performance.analysis_input import analysis_input, analysis_sport
from backend.performance.canonical_detail import (
    SessionRecordReader,
    detail_candidates,
    primary_analysis_record,
)
from backend.performance.pace_at_hr import METHOD as PACE_METHOD
from backend.performance.pace_at_hr import pace_at_heart_rate
from backend.performance.power_profile import (
    METHOD_ID,
    METHOD_VERSION,
    power_profile,
    running_profile,
)
from backend.performance.session_execution import METHOD as EXECUTION_METHOD
from backend.performance.session_execution import (
    comparison_metrics,
    session_execution,
)
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND

_DEFAULT_CAPACITY: Final = 1024


@dataclass(frozen=True, slots=True)
class SessionCurve:
    """The power and running curves and the pace-at-heart-rate bins of one session and the fingerprint of their input."""

    power: dict[str, Any]
    running: dict[str, Any]
    fingerprint: str
    pace_at_hr: dict[str, Any]
    # The comparison numbers of the session's execution (streams and current
    # laps); only these are kept, not the full per-rep execution.
    execution_summary: dict[str, Any] | None = None


class SessionCurveReader:
    """Read session curves, recomputing only sessions whose input changed."""

    def __init__(
        self,
        session_records: SessionRecordReader,
        *,
        capacity: int = _DEFAULT_CAPACITY,
    ) -> None:
        self._session_records = session_records
        self._capacity = capacity
        self._memo: OrderedDict[str, SessionCurve] = OrderedDict()
        self._lock = threading.Lock()

    def curves(
        self,
        db: Any,
        activity_ids: Iterable[str],
        intervals_fingerprints: Mapping[str, str],
    ) -> dict[str, SessionCurve]:
        """Return the curve of each session that has current full-resolution streams.

        ``intervals_fingerprints`` maps an Intervals.icu activity id to the
        fingerprint of its current summary row.
        """
        curves: dict[str, SessionCurve] = {}
        wanted = list(activity_ids)
        keys_by_session = activity_detail_store.full_stream_keys(db, wanted)
        laps_by_session = activity_detail_store.lap_set_keys(db, wanted)
        for activity_id, keys in keys_by_session.items():
            current = _current(db, keys, intervals_fingerprints)
            records = tuple(self._session_records(db, activity_id))
            if not current or not records:
                continue
            laps = _current(
                db, laps_by_session.get(activity_id, ()), intervals_fingerprints
            )
            fingerprint = _fingerprint(records, current, laps)
            with self._lock:
                cached = self._memo.get(fingerprint)
                if cached is not None:
                    self._memo.move_to_end(fingerprint)
            if cached is None:
                cached = _session_curve(
                    db, activity_id, records, current, laps, fingerprint
                )
                with self._lock:
                    self._memo[fingerprint] = cached
                    while len(self._memo) > self._capacity:
                        self._memo.popitem(last=False)
            curves[activity_id] = cached
        return curves


def input_fingerprint(parts: Iterable[object]) -> str:
    """Fingerprint of a result built from several inputs, independent of order."""
    return _sha256(sorted({_canonical(part) for part in parts}))


def _current(
    db: Any,
    keys: Iterable[FullStreamKey],
    intervals_fingerprints: Mapping[str, str],
) -> list[FullStreamKey]:
    """The keys whose sets still belong to the provider's current summary."""
    return [
        key
        for key in keys
        if not _stale(db, key, intervals_fingerprints.get(key.provider_activity_id))
    ]


def _stale(db: Any, key: FullStreamKey, intervals_fingerprint: str | None) -> bool:
    """Whether the provider summary changed since the set was fetched."""
    if key.summary_sha256 is None:
        return False
    if key.provider == ProviderId.INTERVALS.value:
        current = intervals_fingerprint
    else:
        current = canonical_store.active_provider_record_hash(
            db, key.provider, ACTIVITY_RECORD_KIND, key.provider_activity_id
        )
    return current is not None and current != key.summary_sha256


def _session_curve(
    db: Any,
    activity_id: str,
    records: tuple[ActivityRecord, ...],
    keys: Sequence[FullStreamKey],
    laps: Sequence[FullStreamKey],
    fingerprint: str,
) -> SessionCurve:
    # Each kind keeps only its own current sets, so a stale set of one kind
    # never returns through a current set of the other.
    streams_wanted = {(key.provider, key.provider_activity_id) for key in keys}
    laps_wanted = {(key.provider, key.provider_activity_id) for key in laps}
    stored = [
        item
        for item in activity_detail_store.full_stream_sets_for_session(db, activity_id)
        if (item.provider, item.provider_activity_id) in streams_wanted
    ]
    stored += [
        item
        for item in activity_detail_store.lap_sets_for_session(db, activity_id)
        if (item.provider, item.provider_activity_id) in laps_wanted
    ]
    merged = merge_details(detail_candidates(records, stored))
    primary = primary_analysis_record(records)
    adapted = analysis_input(
        primary, merged.streams, merged.laps, members=measured_order(records)
    )
    return SessionCurve(
        power=power_profile(
            adapted.activity, source_label=adapted.label_for("watts", "moving")
        ),
        running=running_profile(
            adapted.activity,
            source_label=adapted.label_for("velocity_smooth", "distance", "moving"),
        ),
        fingerprint=fingerprint,
        pace_at_hr=pace_at_heart_rate(
            adapted.activity,
            source_label=adapted.label_for(
                "velocity_smooth", "heartrate", "grade_smooth", "altitude", "moving"
            ),
        ),
        execution_summary=comparison_metrics(
            session_execution(
                adapted.activity,
                source_label=adapted.label_for(
                    "watts", "heartrate", "velocity_smooth", "cadence", "laps"
                ),
            )
        ),
    )


def _fingerprint(
    records: Sequence[ActivityRecord],
    keys: Sequence[FullStreamKey],
    laps: Sequence[FullStreamKey] = (),
) -> str:
    """Hash every input that changes the merged streams, laps, labels or the sport."""
    return _sha256(
        [
            METHOD_ID,
            METHOD_VERSION,
            PACE_METHOD,
            EXECUTION_METHOD,
            sorted([key.content_sha256, key.fetched_at] for key in laps),
            analysis_sport(primary_analysis_record(records), measured_order(records)),
            sorted(
                _canonical(
                    [
                        record.provenance.provider,
                        record.activity_id,
                        record.started_at,
                        record.device_type,
                        record.provenance.label,
                    ]
                )
                for record in records
            ),
            sorted([key.content_sha256, key.fetched_at] for key in keys),
        ]
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
