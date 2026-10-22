"""The one write path for the Garmin collection payload.

Garmin sync, the Morning Body Battery refresh and the targeted nutrition and
analysis refreshes store what they fetched through ``GarminSnapshotWriter``. Inside
the caller's unit of work it upserts one raw-layer row per changed element, the
canonical activities and observations, the coverage summary and the small
``garmin_state`` value together, so a failure in any of them rolls back all.
A write carries a delta: sections it does not mention stay as they are.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.garmin_payload import (
    ACTIVITIES_SECTION,
    ITEM_SECTIONS,
    REPLACE_SECTIONS,
)
from backend.canonical.section_items import record_id, split_section
from backend.db import garmin_store
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import garmin_payload_retrieved_at
from backend.sync.canonical_coverage_store import (
    CanonicalCoverageStore,
    garmin_ingest_coverage,
)
from backend.sync.canonical_ingest import (
    CanonicalIngestCounters,
    ingest_garmin_payload,
)

# The sections a targeted analysis refresh may write.
ANALYSIS_SOURCES: Final = frozenset(
    {
        "activities",
        "training_load_activities",
        "daily_training_status",
        "training_load_balance",
        "cycling_ftp",
        "running_threshold",
        "race_predictions",
        "max_metrics",
        "cycling_ftp_history",
        "endurance_score",
        "running_tolerance",
        "training_readiness_history",
        "weekly_training_status",
        "sleep",
        "hrv",
        "readiness",
        "daily_stats",
        "resting_hr",
    }
)
NUTRITION_SOURCES: Final = frozenset({"daily_stats", "weight"})


class GarminSnapshotWriter:
    def __init__(
        self,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
    ) -> None:
        self._coverage = CanonicalCoverageStore(key_values)
        self._zone_provider = zone_provider

    def write(self, db: Any, payload: Mapping[str, Any]) -> CanonicalIngestCounters:
        """Write the delta a sync collected: element rows, state and coverage."""
        zone = self._zone_provider() or UTC
        counters = ingest_garmin_payload(db, payload, zone=zone)
        if garmin_payload_retrieved_at(payload, zone=zone) is not None:
            for section in REPLACE_SECTIONS:
                self._replace(db, section, payload.get(section))
        self._patch_state(db, payload)
        self._coverage.persist(
            db, garmin_ingest_coverage(db, payload, zone=zone), zone=zone
        )
        return counters

    def write_refresh(
        self,
        db: Any,
        *,
        fetched_at: str,
        sections: Mapping[str, Any],
        view: Mapping[str, Any],
        windows: Mapping[str, tuple[date, date]],
        allowed: frozenset[str],
    ) -> CanonicalIngestCounters:
        """Write the sections one targeted refresh changed, without restamping others.

        ``sections`` holds the merged value of each refreshed section; ``windows``
        names the sections whose stored elements inside the day range are replaced
        by it (a complete read), so an element the provider no longer returns goes.
        The state keys of ``view`` are patched into the stored state.
        """
        if not set(sections).issubset(allowed):
            raise ValueError("Unsupported Garmin refresh source")
        zone = self._zone_provider() or UTC
        counters = ingest_garmin_payload(
            db, {"synced_at": fetched_at, **sections}, zone=zone
        )
        for section, value in sections.items():
            window = windows.get(section)
            if window is not None:
                self._prune(db, section, value, window)
            elif section in REPLACE_SECTIONS:
                self._replace(db, section, value)
        self._patch_state(db, view)
        return counters

    @staticmethod
    def _replace(db: Any, section: str, value: Any) -> None:
        """Drop the stored elements a non-empty current answer no longer holds.

        A gear inventory is only present after a successful read, so an empty
        list is a real answer there and clears the stored items.
        """
        if value or (section == "gear" and value == []):
            garmin_store.prune_section(db, section, _identifiers(section, value))

    @staticmethod
    def _prune(db: Any, section: str, value: Any, window: tuple[date, date]) -> None:
        if section in ITEM_SECTIONS and section != ACTIVITIES_SECTION:
            garmin_store.prune_section(
                db,
                section,
                _identifiers(section, value),
                start=window[0].isoformat(),
                end=window[1].isoformat(),
            )

    @staticmethod
    def _patch_state(db: Any, payload: Mapping[str, Any]) -> None:
        state = garmin_store.read_state(db)
        state.update(garmin_store.split_state(payload))
        garmin_store.write_state(db, state, now=datetime.now(UTC).isoformat())


def _identifiers(section: str, value: Any) -> set[str]:
    return {record_id(section, item.key) for item in split_section(value)}
