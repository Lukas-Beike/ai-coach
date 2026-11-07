"""Compose the metric export use case with its provider adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId
from backend.performance.canonical_current import read_export_thresholds
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.current_thresholds import ThresholdKey
from backend.performance.source_policy import SourcePreferences
from backend.providers.intervals_client import IntervalsClient
from backend.runtime.ports import ObservationReader
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.intervals_metric_export import IntervalsMetricExport
from backend.sync.metric_export import MetricExportService


def export_thresholds_reader(
    observation_reader: Callable[[], ObservationReader],
    *,
    source_preferences: Callable[[Any], SourcePreferences],
    today: Callable[[], date],
) -> Callable[[Any], dict[ThresholdKey, Observation]]:
    """Return ``db -> thresholds`` an outbound export sends, current today.

    Thresholds are the resolved local, Garmin and Wahoo values. Local zones are
    read from the tables directly, like the zone editor, so a zone saved before
    the first canonical backfill completes is still sent.
    """

    def thresholds(db: Any) -> dict[ThresholdKey, Observation]:
        return read_export_thresholds(
            resolve_reader(observation_reader(), db),
            db,
            as_of=today(),
            preferences=source_preferences(db),
            configurations=CanonicalTableReader().zone_configurations(db),
        )

    return thresholds


def build_metric_export_service(
    database_manager: Callable[[], Any],
    observation_reader: Callable[[], ObservationReader],
    *,
    database_lock: Any,
    intervals_client: Callable[[], IntervalsClient],
    thresholds: Callable[[Any], dict[ThresholdKey, Observation]],
    today: Callable[[], date],
    utc_now: Callable[[], datetime],
) -> MetricExportService:
    """Return the service; a provider client is opened only by a confirmed write.

    ``thresholds`` is the shared ``export_thresholds_reader``.
    """
    return MetricExportService(
        database_manager,
        observation_reader,
        {ProviderId.INTERVALS: lambda: IntervalsMetricExport(intervals_client)},
        thresholds=thresholds,
        database_lock=database_lock,
        today=today,
        utc_now=utc_now,
    )
