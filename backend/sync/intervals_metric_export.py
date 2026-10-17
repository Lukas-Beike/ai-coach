"""Intervals.icu implementation of the metric export port.

REST transport lives in ``backend.providers.intervals_client``. Field names are
the ones the read mapping (``backend.providers.intervals_wellness_mapping``)
accepts, so an exported value reads back as the same canonical metric. The
client is resolved per write, so a preview never opens the transport.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind, Sport
from backend.errors import AppError
from backend.providers.intervals_client import IntervalsClient
from backend.sync.metric_export_port import MetricExportField, MetricWrite

_WELLNESS_RECORD: Final = "wellness"
_SPORT_SETTINGS_RECORD: Final = "sport-settings"
_SPORT_TYPES: Final = {Sport.RIDE: "Ride", Sport.RUN: "Run"}

# Wellness fields are written to the observed day.
_WELLNESS_FIELDS: Final = {
    MetricKind.WEIGHT: "weight",
    MetricKind.BODY_FAT: "bodyFat",
    MetricKind.RESTING_HR: "restingHR",
}
# Sport-setting fields per sport; threshold_pace is a Run setting in m/s.
_SPORT_SETTING_FIELDS: Final = {
    (MetricKind.FTP, Sport.RIDE): "ftp",
    (MetricKind.THRESHOLD_HR, Sport.RIDE): "lthr",
    (MetricKind.THRESHOLD_HR, Sport.RUN): "lthr",
    (MetricKind.MAX_HR, Sport.RIDE): "max_hr",
    (MetricKind.MAX_HR, Sport.RUN): "max_hr",
    (MetricKind.THRESHOLD_PACE, Sport.RUN): "threshold_pace",
}
_DECIMALS: Final = {
    MetricKind.WEIGHT: 2,
    MetricKind.BODY_FAT: 1,
    MetricKind.THRESHOLD_PACE: 4,
}
_SPORT_LABELS: Final = {Sport.RIDE: "Rad", Sport.RUN: "Lauf"}


def _remote_number(kind: MetricKind, value: float) -> float | int:
    decimals = _DECIMALS.get(kind)
    return round(value) if decimals is None else round(value, decimals)


class IntervalsMetricExport:
    supports_hr_zone_recalc = True

    def __init__(self, client_factory: Callable[[], IntervalsClient]) -> None:
        self._client_factory = client_factory

    def field_for(
        self, kind: MetricKind, sport: Sport | None
    ) -> MetricExportField | None:
        wellness = _WELLNESS_FIELDS.get(kind)
        if wellness is not None:
            return MetricExportField(
                kind, None, wellness, True, f"Wellness · {wellness}"
            )
        if sport is None and kind is MetricKind.FTP:
            # Untagged FTP is cycling power, as on the Intervals.icu read side.
            sport = Sport.RIDE
        if sport is None:
            return None
        setting = _SPORT_SETTING_FIELDS.get((kind, sport))
        if setting is None:
            return None
        return MetricExportField(
            kind,
            sport,
            setting,
            False,
            f"Sporteinstellungen {_SPORT_LABELS[sport]} · {setting}",
        )

    def remote_record(self, field: MetricExportField, observed_on: date) -> str:
        if field.dated:
            return f"{_WELLNESS_RECORD}/{observed_on.isoformat()}"
        if field.sport is None:
            raise ValueError("A sport-settings field needs a sport.")
        return f"{_SPORT_SETTINGS_RECORD}/{_SPORT_TYPES[field.sport]}"

    def write(self, writes: Sequence[MetricWrite], *, recalc_hr_zones: bool) -> None:
        if not writes:
            return
        first = writes[0]
        record = self.remote_record(first.field, first.observed_on)
        if any(
            self.remote_record(item.field, item.observed_on) != record
            for item in writes
        ):
            raise ValueError("One write must target one remote record.")
        fields: dict[str, Any] = {
            item.field.field: _remote_number(item.field.kind, item.value)
            for item in writes
        }
        client = self._client_factory()
        if first.field.dated:
            result = client.update_wellness(first.observed_on.isoformat(), fields)
        else:
            assert first.field.sport is not None
            result = client.update_sport_settings(
                _SPORT_TYPES[first.field.sport],
                fields,
                recalc_hr_zones=recalc_hr_zones,
            )
        if not isinstance(result, dict):
            raise AppError(
                502,
                "Intervals.icu hat die Werte nicht bestätigt.",
                reason="upstream_invalid_response",
            )
