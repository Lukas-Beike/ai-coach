"""Read use case of the ``activity_detail.v1`` document of one canonical session.

The document combines the session's stored detail sets, its active activity
records and the stored target and decoupling values of the session analysis. The
analysis is recomputed from the merged streams at read time. The caller owns the
transaction: ``db`` is an open connection and this module only reads from it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from backend.activities.detail_contract import activity_detail_contract, measured_order
from backend.activities.detail_merge import DetailCandidate, merge_details
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ProviderId
from backend.db import activity_detail_store
from backend.performance.analysis_input import analysis_input
from backend.performance.power_profile import power_profile, running_profile
from backend.performance.session_analysis import aerobic_analysis, interval_quality


class SessionRecordReader(Protocol):
    """Return the active activity records of one canonical session."""

    def __call__(self, db: Any, activity_id: str) -> Sequence[ActivityRecord]: ...


class CanonicalDetailReader:
    """Serve the ``activity_detail.v1`` document of a canonical session."""

    def __init__(
        self,
        session_records: SessionRecordReader,
        *,
        refreshable: frozenset[ProviderId],
    ) -> None:
        self._session_records = session_records
        self._refreshable = refreshable

    def read(self, db: Any, activity_id: str) -> dict[str, Any] | None:
        """Return the document, or None when the session has no readable records."""
        records = tuple(self._session_records(db, activity_id))
        if not records:
            return None
        stored = activity_detail_store.detail_sets_for_session(db, activity_id)
        by_key = {
            (_provider_text(record), record.activity_id): record for record in records
        }
        candidates = []
        for item in stored:
            record = by_key.get((item.provider, item.provider_activity_id))
            if record is not None:
                candidates.append(
                    DetailCandidate(
                        stored=item,
                        started_at=record.started_at,
                        device_type=record.device_type,
                    )
                )
        merged = merge_details(candidates)
        ordered = measured_order(records)
        analysis_record = next(
            (r for r in ordered if r.provenance.provider is ProviderId.INTERVALS),
            ordered[0],
        )
        payload = _stored_payload(db, activity_id)
        adapted = analysis_input(
            analysis_record,
            merged.streams,
            merged.laps,
            decoupling=_decoupling(payload),
        )
        targets = payload.get("target_snapshot")
        # Each analysis credits only the providers of the channels it reads.
        analysis = {
            "interval_quality": interval_quality(
                adapted.activity,
                targets if isinstance(targets, dict) else None,
                source_label=adapted.label_for(
                    "watts", "heartrate", "velocity_smooth", "laps"
                ),
            ),
            "aerobic": aerobic_analysis(
                adapted.activity,
                source_label=adapted.label_for(
                    "watts", "heartrate", "velocity_smooth", "moving"
                ),
            ),
            "power_profile": power_profile(
                adapted.activity, source_label=adapted.label_for("watts", "moving")
            ),
            "running_profile": running_profile(
                adapted.activity,
                source_label=adapted.label_for("velocity_smooth", "distance", "moving"),
            ),
        }
        return activity_detail_contract(
            activity_id,
            records,
            merged,
            stored,
            analysis=analysis,
            refreshable=self._refreshable,
        )


def _provider_text(record: ActivityRecord) -> str | None:
    provider = record.provenance.provider
    return None if provider is None else provider.value


def _stored_payload(db: Any, activity_id: str) -> dict[str, Any]:
    row = activity_detail_store.analysis_rows_for(db, [activity_id]).get(activity_id)
    if row is None:
        return {}
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _decoupling(payload: Mapping[str, Any]) -> float | None:
    """Return the stored provider decoupling when it is a finite number."""
    session = payload.get("session_analysis")
    aerobic = session.get("aerobic") if isinstance(session, dict) else None
    provider = aerobic.get("provider_decoupling") if isinstance(aerobic, dict) else None
    value = provider.get("value") if isinstance(provider, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None
