"""Recognise repeated outdoor routes from the stored GPS tracks (#1868).

``ActivityRoutesStage`` is a follow-up stage of the canonical backfill worker.
Per ride or run not known to be indoor or virtual (Garmin's generic running and
cycling types map to an unknown environment) it fingerprints the stream content
hashes, the start and the distance before any stream is decoded; only sessions
whose stored input hash differs are decoded, fingerprinted
(``backend.activities.routes``) and placed, oldest first, so a pass without
changes decodes nothing. The worker's ``prefetch`` decodes and fingerprints the
batch with a reader first, so the writer transaction only re-checks the input
hashes and places the tracks (#2311). Sessions that are gone and routes without a session
leave the index, athlete names stay on the routes that remain. Nothing is
requested remotely.

Turning "GPS-Spuren speichern" off keeps the index. It is removed only with the
confirmed GPS-track deletion or the purge (``route_store.clear_routes``).
Positions live only in local variables of the decoding; the
state and the log carry counts.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Mapping
from datetime import UTC, tzinfo
from typing import Any, Final

from backend.activities import route_store, routes
from backend.activities.activity_summary import activity_summaries
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import fingerprint_inputs
from backend.canonical.sports import is_outdoor_endurance
from backend.canonical.vocabulary import (
    PROVIDER_PRECEDENCE,
    ProviderId,
    StreamChannel,
)
from backend.db import activity_detail_store
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_backfill import (
    BatchReport,
    precomputed_batch,
    timed_batch,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "activity_routes"
STATE_KEY: Final = route_store.STATE_KEY
METHOD_VERSION: Final = 1
DEFAULT_BATCH_SIZE: Final = 50
_INTERVALS: Final = ProviderId.INTERVALS.value
_RANK: Final = {
    provider.value: index for index, provider in enumerate(PROVIDER_PRECEDENCE)
}


def _wants(summary: Mapping[str, Any]) -> bool:
    """A ride or run that may have a track; the track itself decides later."""
    return is_outdoor_endurance(
        str(summary.get("sport")), str(summary.get("environment"))
    )


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _input_hash(summary: Mapping[str, Any], stream_hashes: list[str]) -> str:
    """Every input of a session's fingerprint, known without decoding a stream."""
    return fingerprint_inputs(
        {
            "method_version": METHOD_VERSION,
            "started_at": summary.get("started_at"),
            "distance_m": _finite(summary.get("distance_m")),
            "streams": sorted(stream_hashes),
        }
    )


def _track(
    db: Any, session_id: str, distance_m: float | None
) -> routes.Fingerprint | None:
    """The fingerprint of the session's own track; the best provider with one wins."""
    sets = sorted(
        (
            item
            for item in activity_detail_store.full_stream_sets_for_session(
                db, session_id
            )
            if item.provider != _INTERVALS
        ),
        key=lambda item: _RANK.get(item.provider, len(_RANK)),
    )
    for item in sets:
        detail = item.detail
        if not isinstance(detail, ActivityStreamSet):
            continue
        found = routes.fingerprint(
            detail.channels.get(StreamChannel.LATITUDE_DEG, ()),
            detail.channels.get(StreamChannel.LONGITUDE_DEG, ()),
            distance_m,
        )
        if found is not None:
            return found
    return None


class ActivityRoutesStage:
    """Backfill follow-up that keeps the route index current."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        reader: CanonicalTableReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._reader = reader or CanonicalTableReader()
        self._batch_size = batch_size
        self._prepared: dict[str, tuple[str, routes.Fingerprint | None]] | None = None

    @property
    def stage(self) -> str:
        return STAGE

    def prefetch(self, database: Callable[[], Any]) -> None:
        """Decode one batch of changed tracks with a reader, before the writer."""
        prepared: dict[str, tuple[str, routes.Fingerprint | None]] = {}
        try:
            with database().reader() as db:
                wanted, hashes, changed = self._changed(db, route_store.load_index(db))
                for session_id in timed_batch(changed, self._batch_size):
                    prepared[session_id] = (
                        hashes[session_id],
                        _track(db, session_id, wanted[session_id].get("distance_m")),
                    )
        except Exception as error:  # noqa: BLE001 - the writer batch computes inline
            _LOGGER.warning(
                "Route prefetch failed",
                extra={
                    "event": "activity_routes_failed",
                    "context": {"error_type": type(error).__name__},
                },
            )
            prepared = {}
        self._prepared = prepared

    def run_batch(self, db: Any) -> BatchReport:
        """Place one batch; a failure is logged and never blocks later stages."""
        try:
            return self._run_batch(db)
        except Exception as error:  # noqa: BLE001 - isolate this cosmetic stage
            _LOGGER.warning(
                "Route batch failed",
                extra={
                    "event": "activity_routes_failed",
                    "context": {"error_type": type(error).__name__},
                },
            )
            self.mark_failed(db)
            return BatchReport(items=0, done=True)

    def _run_batch(self, db: Any) -> BatchReport:
        """Place one batch of changed sessions in the caller's transaction."""
        prepared, self._prepared = self._prepared, None
        index = route_store.load_index(db)
        before = json.dumps(index, sort_keys=True)
        wanted, hashes, changed = self._changed(db, index)
        sessions = index["sessions"]
        placed = 0
        for session_id, track in precomputed_batch(
            [(session_id, hashes[session_id], session_id) for session_id in changed],
            self._batch_size,
            prepared,
            lambda session_id: _track(
                db, session_id, wanted[session_id].get("distance_m")
            ),
        ):
            placed += 1
            summary = wanted[session_id]
            sessions.setdefault(session_id, {"route": None})
            sessions[session_id].update(h=hashes[session_id], at=summary["started_at"])
            routes.place(index, session_id, track)
        routes.prune(index, wanted)
        if json.dumps(index, sort_keys=True) != before:
            route_store.save_index(self._key_values, db, index)
        remaining = len(changed) - placed
        counts = {
            "sessions": len(wanted),
            "placed": placed,
            "routes": len(index["routes"]),
            "with_route": sum(1 for item in sessions.values() if item.get("route")),
            "remaining": remaining,
        }
        self._save(
            db,
            {
                "status": "running" if remaining else "complete",
                "method_version": METHOD_VERSION,
                "counts": counts,
            },
        )
        # Counts only: never a position, a cell, a name or a session id.
        _LOGGER.info(
            "Activity routes reconciled",
            extra={"event": "activity_routes_reconciled", "context": counts},
        )
        return BatchReport(items=placed, done=remaining == 0)

    def mark_failed(self, db: Any) -> None:
        state = _load_state(self._key_values, db)
        state["status"] = "failed"
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free status and counts of the last batch."""
        return summarize_activity_routes(self._key_values, db)

    def _changed(
        self, db: Any, index: Mapping[str, Any]
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], list[str]]:
        """Wanted sessions, their input hashes, and the ids whose hash changed."""
        wanted = self._wanted(db)
        keys = activity_detail_store.full_stream_keys(db, list(wanted))
        hashes = {
            session_id: _input_hash(
                summary,
                [
                    key.content_sha256
                    for key in keys.get(session_id, ())
                    if key.provider != _INTERVALS
                ],
            )
            for session_id, summary in wanted.items()
        }
        changed = [
            session_id
            for session_id, digest in hashes.items()
            if index["sessions"].get(session_id, {}).get("h") != digest
        ]
        return wanted, hashes, changed

    def _wanted(self, db: Any) -> dict[str, Mapping[str, Any]]:
        """Rides and runs not known to be indoor, by session id, oldest first."""
        sessions = [
            (session_id, records)
            for session_id, records in self._reader.activity_sessions(db)
            if records
        ]
        summaries = [
            summary
            for summary in activity_summaries(sessions, self._zone_provider() or UTC)
            if _wants(summary)
        ]
        summaries.sort(key=lambda item: (str(item.get("started_at")), str(item["id"])))
        return {str(summary["id"]): summary for summary in summaries}

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def summarize_activity_routes(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status and counts of the last batch, for diagnostics."""
    state = _load_state(key_values, db)
    return {
        "status": state.get("status", "pending"),
        "method_version": state.get("method_version"),
        "counts": state.get("counts", {}),
    }
