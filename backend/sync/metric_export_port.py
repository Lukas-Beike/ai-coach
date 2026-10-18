"""Provider-neutral outbound port for explicitly confirmed metric exports.

A port maps canonical body and threshold metrics onto one target's fields,
reads the fields' current remote values and writes them. The service owns
explicit manual confirmations and persisted athlete consent for automatic
Garmin synchronization; the port never decides when a remote write happens.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from backend.canonical.vocabulary import MetricKind, Sport


@dataclass(frozen=True, slots=True)
class MetricExportField:
    """One target field that receives a canonical metric.

    ``dated`` fields hold one value per day (the observed day is written);
    undated fields hold the target's current setting. ``zone_recalc`` fields are
    written with the target's optional heart-rate zone recalculation.
    """

    kind: MetricKind
    sport: Sport | None
    field: str
    dated: bool
    label: str
    zone_recalc: bool = False


@dataclass(frozen=True, slots=True)
class MetricWrite:
    field: MetricExportField
    value: float
    observed_on: date


@runtime_checkable
class MetricExportPort(Protocol):
    @property
    def supports_hr_zone_recalc(self) -> bool:
        """Return whether the target can recalculate heart-rate zones on write."""

    def field_for(
        self, kind: MetricKind, sport: Sport | None
    ) -> MetricExportField | None:
        """Return the target field for a metric and sport, or None when unsupported."""

    def remote_record(self, field: MetricExportField, observed_on: date) -> str:
        """Return the remote record that holds the field; writes are grouped by it."""

    def normalize_value(self, field: MetricExportField, value: float) -> float:
        """Return the numeric value the target will store after a write."""

    def read_record(
        self, field: MetricExportField, observed_on: date
    ) -> Mapping[str, float]:
        """Return the numeric fields the target currently stores in the field's record.

        A missing record reads as empty. Failures raise an AppError without the
        target's raw error text.
        """

    def write(self, writes: Sequence[MetricWrite], *, recalc_hr_zones: bool) -> None:
        """Write one remote record's fields; only the given fields may change.

        Failures raise an AppError without the target's raw error text.
        """
