from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Protocol, runtime_checkable

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, Sport


class ProviderSnapshotReader(Protocol):
    def latest_snapshot(self, db: Any) -> dict[str, Any] | None: ...


class ProviderStateReader(Protocol):
    def summary(self, provider: str) -> dict[str, Any]: ...


class AudioTranscriber(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> dict[str, str]: ...


class ActivityReader(Protocol):
    """Reads canonical activity records.

    ``start`` and ``end`` are inclusive bounds on the athlete-local date of each
    activity's start. Results contain validated canonical records only; mapping
    issues are not returned here and are exposed only as counts through
    ``ProviderCoverageReader``.
    """

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]: ...


class ActivityRowReader(Protocol):
    """Reads the raw Intervals.icu activity payloads behind the canonical records.

    Rows are provider dictionaries (device source, ``icu_*`` fields, laps, gear),
    untrusted data, before any de-duplication. ``start`` and ``end`` are inclusive
    bounds on the athlete-local date of each activity, as in ``ActivityReader``.
    Deleted or tombstoned activities are never returned. The legacy source keeps
    the snapshot order (newest first); the table source orders newest first by
    activity start, then id.
    """

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[dict[str, Any], ...]: ...


class ObservationReader(Protocol):
    """Reads canonical observations of one metric kind.

    ``start`` and ``end`` are inclusive bounds on each observation's
    ``observed_on`` date. ``sport`` restricts results to one sport when given.
    Results contain validated canonical observations only; mapping issues are
    exposed only as counts through ``ProviderCoverageReader``.
    """

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]: ...


@runtime_checkable
class ObservationSourceSelector(ObservationReader, Protocol):
    """An observation reader that chooses its serving source for every read.

    ``reader_for`` makes that choice once and returns the chosen reader, so a
    caller with several reads in one unit of work does not repeat it per read.
    """

    def reader_for(self, db: Any) -> ObservationReader: ...


class ProviderCoverageReader(Protocol):
    """Reports per-provider coverage counts, including mapping issue counts only."""

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]: ...


class CanonicalReadRefresher(Protocol):
    """Re-checks which canonical source serves reads and records the result.

    Both methods write only their own content-free switch state, in the caller's
    transaction. ``record_failure`` receives the exception class name only.
    """

    def refresh(self, db: Any) -> None: ...

    def record_failure(self, db: Any, error_class: str) -> None: ...


class CanonicalTableServing(Protocol):
    """Reports whether reads are currently served from the canonical tables.

    True only when the backfill is complete and the last parity check passed for
    the current digest. Callers read table-only data only while this holds.
    """

    def serves_tables(self, db: Any) -> bool: ...


ProviderOperation = Callable[[], AbstractContextManager[None]]
