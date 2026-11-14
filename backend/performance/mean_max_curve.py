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

import contextvars
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from backend.activities.detail_contract import measured_order
from backend.activities.detail_merge import merge_details
from backend.canonical.records import ActivityRecord
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import FullStreamKey
from backend.performance.analysis_input import analysis_input, analysis_sport
from backend.performance.canonical_detail import (
    SessionRecordReader,
    detail_candidates,
    primary_analysis_record,
)
from backend.performance.pace_at_hr import METHOD as PACE_METHOD
from backend.performance.pace_at_hr import (
    POWER_METHOD,
    pace_at_heart_rate,
    power_at_heart_rate,
)
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

_LOGGER = logging.getLogger("intervals_coach")
# About 9 KB per session; room for a long all-time history (#2694).
_DEFAULT_CAPACITY: Final = 2048
# A failed background build is tried again after this pause.
_RETRY_AFTER_S: Final = 60.0


@dataclass(frozen=True, slots=True)
class SessionCurve:
    """The power and running curves, the pace- and power-at-heart-rate bins of one session and the fingerprint of their input."""

    power: dict[str, Any]
    running: dict[str, Any]
    fingerprint: str
    pace_at_hr: dict[str, Any]
    power_at_hr: dict[str, Any]
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
        spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._session_records = session_records
        self._capacity = capacity
        self._memo: OrderedDict[str, SessionCurve] = OrderedDict()
        self._shared: tuple[str, tuple[Mapping[str, Any], ...]] | None = None
        self._background: tuple[str, tuple[Mapping[str, Any], ...]] | None = None
        self._building = False
        self._failed: tuple[str, float] | None = None
        self._spawn = spawn or _daemon_thread
        self._lock = threading.Lock()

    def curves(self, db: Any, activity_ids: Iterable[str]) -> dict[str, SessionCurve]:
        """Return the curve of each session that has current full-resolution streams."""
        curves: dict[str, SessionCurve] = {}
        wanted = list(activity_ids)
        keys_by_session = activity_detail_store.full_stream_keys(db, wanted)
        laps_by_session = activity_detail_store.lap_set_keys(db, wanted)
        for activity_id, keys in keys_by_session.items():
            current = _current(db, keys)
            records = tuple(self._session_records(db, activity_id))
            if not current or not records:
                continue
            laps = _current(db, laps_by_session.get(activity_id, ()))
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

    def shared_records(
        self,
        db: Any,
        activity_ids: Sequence[str],
        key: object,
        build: Callable[[], Iterable[Mapping[str, Any]]],
    ) -> tuple[Mapping[str, Any], ...]:
        """Return the last built session records while their inputs are unchanged.

        The stamp is ``key`` (what the caller's records show of the sessions) with
        the stored records and detail sets of ``activity_ids`` that ``curves``
        reads, so a new day, session or merge, or a changed stream, lap set or
        provider summary builds the records again, and an unchanged read queries no
        session. Callers share one tuple of read-only records. Of concurrent
        builds the first to finish is kept: a build stores its result only if the
        slot still holds what it held when the call started, and the next read
        rebuilds if that result is no longer current. Concurrent misses each build
        once; the per-session memo makes the repeat cheap.
        """
        stamp = _stamp(db, activity_ids, key)
        with self._lock:
            held = self._shared[0] if self._shared else None
            if self._shared and held == stamp:
                return self._shared[1]
        records = tuple(MappingProxyType(record) for record in build())
        with self._lock:
            if (self._shared[0] if self._shared else None) == held:
                self._shared = (stamp, records)
        return records

    def background_records(
        self,
        db: Any,
        activity_ids: Sequence[str],
        key: object,
        build: Callable[[], Iterable[Mapping[str, Any]]],
    ) -> tuple[tuple[Mapping[str, Any], ...], bool] | None:
        """Return records built off the caller's path and whether they are current (#2694).

        Stamped like ``shared_records``, in a slot of its own. A changed stamp
        never builds in the caller: it starts ``build`` once in the background
        (it opens its own reads; the per-session memo keeps a rebuild after a new
        session cheap) and returns the last finished records meanwhile, marked
        not current, None before the first. A failed build is logged; for
        ``_RETRY_AFTER_S`` the same stamp raises RuntimeError instead of building
        again.
        """
        stamp = _stamp(db, activity_ids, key)
        with self._lock:
            ready = self._background
            if ready and ready[0] == stamp:
                return ready[1], True
            failed = self._failed
            if (
                failed
                and failed[0] == stamp
                and time.monotonic() - failed[1] < _RETRY_AFTER_S
            ):
                raise RuntimeError("background session curves failed")
            start = not self._building
            self._building = True
        if start:
            try:
                self._spawn(lambda: self._build_in_background(stamp, build))
            except BaseException:
                with self._lock:
                    self._building = False
                raise
        with self._lock:
            ready = self._background
        return None if ready is None else (ready[1], ready[0] == stamp)

    def _build_in_background(
        self, stamp: str, build: Callable[[], Iterable[Mapping[str, Any]]]
    ) -> None:
        built = None
        try:
            built = tuple(MappingProxyType(record) for record in build())
        except Exception:
            _LOGGER.exception(
                "Background session curves failed",
                extra={"event": "background_session_curves_failed"},
            )
        with self._lock:
            if built is None:
                self._failed = (stamp, time.monotonic())
            else:
                self._background, self._failed = (stamp, built), None
            self._building = False


def _daemon_thread(run: Callable[[], None]) -> None:
    """Run ``run`` in a daemon thread with a fresh context (no request state)."""
    threading.Thread(
        target=contextvars.Context().run,
        args=(run,),
        name="session-curves",
        daemon=True,
    ).start()


def _stamp(db: Any, activity_ids: Sequence[str], key: object) -> str:
    """``key`` with the stored records and detail sets the curves of the sessions read."""
    return _sha256(
        [
            key,
            activity_detail_store.session_curve_inputs(
                db, activity_ids, ACTIVITY_RECORD_KIND
            ),
        ]
    )


def input_fingerprint(parts: Iterable[object]) -> str:
    """Fingerprint of a result built from several inputs, independent of order."""
    return _sha256(sorted({_canonical(part) for part in parts}))


def _current(db: Any, keys: Iterable[FullStreamKey]) -> list[FullStreamKey]:
    """The keys whose sets still belong to the provider's current summary."""
    return [key for key in keys if not _stale(db, key)]


def _stale(db: Any, key: FullStreamKey) -> bool:
    """Whether the provider summary changed since the set was fetched."""
    if key.summary_sha256 is None:
        return False
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
        power_at_hr=power_at_heart_rate(
            adapted.activity,
            source_label=adapted.label_for("watts", "heartrate", "moving"),
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
            POWER_METHOD,
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
