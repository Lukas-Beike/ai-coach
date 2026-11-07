"""Backfill Garmin wellness history once, one bounded window per job.

The ``wellness_backfill`` chain walks back from the automatic refresh window to
the history floor, like the activity backfill, but reads only sleep, HRV, daily
summaries (with their resting heart rate) and weigh-ins. It is insert-only:

* an element whose day is already stored stays as it is, except a stored sleep
  night without night values, which the full night element of the same night
  replaces (athlete decision 2026-11-06), so it gains SpO2, respiration and
  sleeping heart rate;
* the weigh-ins merge into the stored weight envelope, the stored readings win;
* nothing is pruned in a window, so no element or observation is retired.

A complete window moves the ``wellness_history`` cursor to its first day; the
startup scheduler resumes below it after a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any, Final, Protocol

from backend.canonical.section_items import SectionItem, split_section
from backend.db import garmin_store
from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import merge_weight_snapshots
from backend.providers.garmin_wellness_history import (
    WellnessSourcePaused,
    has_night_values,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.jobs import WELLNESS_HISTORY_CURSOR

ITEM_SOURCES: Final = ("sleep", "hrv", "daily_stats", "resting_hr")
WELLNESS_SOURCES: Final = frozenset((*ITEM_SOURCES, "weight"))
# A backfill chunk waits this long for a running Garmin sync before it fails.
LOCK_WAIT_SECONDS: Final = 120.0


class WellnessHistoryReader(Protocol):
    def fetch_wellness_history(
        self, start: date, end: date, *, needs_night: Callable[[str], bool]
    ) -> dict[str, Any]: ...


class SyncCoordination(Protocol):
    def operation(self) -> Any: ...

    def acquire(self, *, timeout: float | None = None) -> bool: ...

    def release(self) -> None: ...


class CursorWriter(Protocol):
    def update_cursor(
        self,
        provider: str,
        stream: str,
        cursor: str,
        high_water_mark: str | None = None,
    ) -> None: ...


class GarminWellnessHistoryService:
    """Read one wellness history window and add what is not stored yet."""

    def __init__(
        self,
        *,
        reader: WellnessHistoryReader,
        database_manager: Any,
        snapshot_writer: GarminSnapshotWriter,
        sync_state_repository: CursorWriter,
        coordination: SyncCoordination,
        utc_now: Callable[[], str],
        configured: Callable[[], bool],
    ) -> None:
        self._reader = reader
        self._database_manager = database_manager
        self._snapshot_writer = snapshot_writer
        self._sync_state = sync_state_repository
        self._coordination = coordination
        self._utc_now = utc_now
        self._configured = configured

    def available(self) -> bool:
        """Return whether a real Garmin read is configured (never in fixture mode)."""
        return self._configured()

    def backfill(self, days: int, end: date) -> dict[str, Any]:
        """Backfill ``days`` days ending on ``end``; return the job result.

        A paused source or a retryable provider error fails the job, so the
        worker retries it later and the cursor stays where it is.
        """
        if not self._configured():
            raise AppError(
                503, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        start = end - timedelta(days=max(1, days) - 1)
        with self._coordination.operation():
            if not self._coordination.acquire(timeout=LOCK_WAIT_SECONDS):
                raise AppError(
                    503, "Garmin wird bereits aktualisiert.", reason="provider_busy"
                )
            try:
                payload = self._reader.fetch_wellness_history(
                    start, end, needs_night=self._needs_night
                )
                fetched_at = self._utc_now()
                written = self._write(payload, fetched_at)
            except WellnessSourcePaused as paused:
                raise AppError(
                    429,
                    "Garmin pausiert nach wiederholten Fehlern.",
                    reason="rate_limited",
                ) from paused
            finally:
                self._coordination.release()
        self._sync_state.update_cursor(
            GARMIN_ID, WELLNESS_HISTORY_CURSOR, start.isoformat(), fetched_at
        )
        pagination = payload["provider_sync"]["pagination"]
        return {
            "status": "ok",
            "synced_at": fetched_at,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "skipped_sources": list(payload["skipped_sources"]),
            "window_records": sum(
                int(details.get("records") or 0) for details in pagination.values()
            ),
            "written": written,
        }

    def _needs_night(self, day: str) -> bool:
        """A night needs its full element unless the stored one has night values."""
        with self._database_manager.reader() as db:
            return not has_night_values(garmin_store.read_item(db, "sleep", day))

    def _write(self, payload: Mapping[str, Any], fetched_at: str) -> dict[str, int]:
        """Write the new elements in one transaction; return their count per source."""
        with self._database_manager.unit_of_work() as db:
            sections: dict[str, Any] = {}
            for source in ITEM_SOURCES:
                records = payload.get(source)
                if not isinstance(records, list):
                    continue
                kept = [
                    item.value
                    for item in split_section(records)
                    if _insertable(db, source, item)
                ]
                if kept:
                    sections[source] = kept
            weight = _merged_weight(db, payload.get("weight"))
            if weight is not None:
                sections["weight"] = weight
            if sections:
                self._snapshot_writer.write_refresh(
                    db,
                    fetched_at=fetched_at,
                    sections=sections,
                    view={},
                    windows={},
                    allowed=WELLNESS_SOURCES,
                )
        return {
            source: len(value) if source != "weight" else 1
            for source, value in sections.items()
        }


def _merged_weight(db: Any, weigh_ins: Any) -> list[Any] | None:
    """Return the stored envelope plus new readings, or None when nothing is new.

    The stored envelope is the incoming side of the merge, so its readings win.
    """
    if not weigh_ins:
        return None
    stored = garmin_store.read_view(db, ["weight"]).get("weight")
    merged = merge_weight_snapshots(stored, weigh_ins)
    # The same merge without new weigh-ins is the stored stock in envelope form.
    if stored and merged == merge_weight_snapshots(stored, None):
        return None
    return merged


def _insertable(db: Any, source: str, item: SectionItem) -> bool:
    """Return whether an element is new, or a full night for a stored bare night."""
    stored = garmin_store.read_item(db, source, item.key)
    if stored is None:
        return True
    return (
        source == "sleep"
        and has_night_values(item.value)
        and not has_night_values(stored)
    )
