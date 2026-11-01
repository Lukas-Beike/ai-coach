"""Per-session mean-maximal curves from canonical full-resolution streams.

Only stream sets stored at full resolution are read: a downsampled set never
enters a best value. A session counts once, with the streams of every record
bundled in it merged as in the activity detail. Curves are computed at read time
and kept in memory under a fingerprint of the method, the session's sport and
environment and the content hashes of its stream sets, so any source change or
new method version recomputes them. Nothing is persisted; reads never touch a
provider.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from backend.activities.detail_merge import merge_details
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.vocabulary import StreamResolution
from backend.db import activity_detail_store
from backend.performance.analysis_input import analysis_input, analysis_sport
from backend.performance.canonical_detail import (
    SessionRecordReader,
    detail_candidates,
    primary_analysis_record,
)
from backend.performance.power_profile import (
    METHOD_ID,
    METHOD_VERSION,
    power_profile,
    running_profile,
)

_DEFAULT_CAPACITY: Final = 1024


@dataclass(frozen=True, slots=True)
class SessionCurve:
    """The power and running curves of one session and the fingerprint of their input."""

    power: dict[str, Any]
    running: dict[str, Any]
    fingerprint: str


class SessionCurveReader:
    """Read session curves, recomputing only sessions whose input changed."""

    def __init__(
        self, session_records: SessionRecordReader, *, capacity: int = _DEFAULT_CAPACITY
    ) -> None:
        self._session_records = session_records
        self._capacity = capacity
        self._memo: OrderedDict[str, SessionCurve] = OrderedDict()
        self._lock = threading.Lock()

    def curves(self, db: Any, activity_ids: Iterable[str]) -> dict[str, SessionCurve]:
        """Return the curve of each session that has full-resolution streams."""
        hashes = activity_detail_store.full_stream_hashes(db, activity_ids)
        curves: dict[str, SessionCurve] = {}
        for activity_id, content in hashes.items():
            records = tuple(self._session_records(db, activity_id))
            if not records:
                continue
            fingerprint = _fingerprint(
                analysis_sport(primary_analysis_record(records)), content
            )
            with self._lock:
                cached = self._memo.get(fingerprint)
                if cached is not None:
                    self._memo.move_to_end(fingerprint)
            if cached is None:
                cached = _session_curve(db, activity_id, records, fingerprint)
                with self._lock:
                    self._memo[fingerprint] = cached
                    while len(self._memo) > self._capacity:
                        self._memo.popitem(last=False)
            curves[activity_id] = cached
        return curves


def input_fingerprint(fingerprints: Iterable[str]) -> str:
    """Fingerprint of a curve built from several sessions, independent of order."""
    return _sha256(sorted(set(fingerprints)))


def _session_curve(
    db: Any, activity_id: str, records: tuple[Any, ...], fingerprint: str
) -> SessionCurve:
    stored = [
        item
        for item in activity_detail_store.detail_sets_for_session(db, activity_id)
        if isinstance(item.detail, ActivityStreamSet)
        and item.detail.resolution is StreamResolution.FULL
    ]
    merged = merge_details(detail_candidates(records, stored))
    adapted = analysis_input(primary_analysis_record(records), merged.streams, None)
    return SessionCurve(
        power=power_profile(
            adapted.activity, source_label=adapted.label_for("watts", "moving")
        ),
        running=running_profile(
            adapted.activity,
            source_label=adapted.label_for("velocity_smooth", "distance", "moving"),
        ),
        fingerprint=fingerprint,
    )


def _fingerprint(sport: dict[str, Any], content: tuple[str, ...]) -> str:
    return _sha256([METHOD_ID, METHOD_VERSION, sport, list(content)])


def _sha256(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
