"""Compose the metric export use case with its provider adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.performance.canonical_current import read_export_thresholds
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.source_policy import SourcePreferences
from backend.providers.intervals_client import IntervalsClient
from backend.runtime.ports import ObservationReader
from backend.sync.intervals_metric_export import IntervalsMetricExport
from backend.sync.metric_export import MetricExportService


def build_metric_export_service(
    database_manager: Callable[[], Any],
    observation_reader: Callable[[], ObservationReader],
    *,
    database_lock: Any,
    intervals_client: Callable[[], IntervalsClient],
    source_preferences: Callable[[Any], SourcePreferences],
    today: Callable[[], date],
    utc_now: Callable[[], datetime],
) -> MetricExportService:
    """Return the service; a provider client is opened only by a confirmed write.

    Thresholds are the resolved local, Garmin and Wahoo values current today.
    """

    def thresholds(db: Any) -> Any:
        return read_export_thresholds(
            resolve_reader(observation_reader(), db),
            db,
            as_of=today(),
            preferences=source_preferences(db),
        )

    return MetricExportService(
        database_manager,
        observation_reader,
        {ProviderId.INTERVALS: lambda: IntervalsMetricExport(intervals_client)},
        thresholds=thresholds,
        database_lock=database_lock,
        today=today,
        utc_now=utc_now,
    )
