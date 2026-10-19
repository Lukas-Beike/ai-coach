"""Canonical merged detail as the legacy input of the session analysis.

The analysis functions read the Intervals.icu-shaped activity dict. This pure
adapter builds that dict from merged canonical streams and laps of any
provider. It never mutates its inputs and performs no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.activities.detail_merge import MergedStreams, SetChoice
from backend.canonical.activity_detail import ActivityLapSet
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import Environment, Sport, StreamChannel

# Canonical channels and the legacy stream keys the analysis reads them from.
_STREAM_KEYS: tuple[tuple[StreamChannel, str], ...] = (
    (StreamChannel.POWER_W, "watts"),
    (StreamChannel.HEART_RATE_BPM, "heartrate"),
    (StreamChannel.SPEED_MPS, "velocity_smooth"),
    (StreamChannel.DISTANCE_M, "distance"),
    (StreamChannel.MOVING, "moving"),
)


_MOVING_FLAGS: dict[float, bool] = {1.0: True, 0.0: False}


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    """Legacy-shaped activity dict and the provider label of its streams."""

    activity: dict[str, Any]
    source_label: str


def analysis_input(
    record: ActivityRecord,
    streams: MergedStreams | None,
    laps: SetChoice | None,
    *,
    decoupling: float | None = None,
) -> AnalysisInput:
    """Build the analysis input of one activity from its merged detail."""
    stream_fields, labels = _streams(streams)
    activity: dict[str, Any] = {
        "type": _activity_type(record),
        "decoupling": decoupling,
        "streams": stream_fields,
        "laps": _laps(laps),
    }
    return AnalysisInput(
        activity=activity,
        source_label=" / ".join(labels) if labels else _label(record.provenance),
    )


def _activity_type(record: ActivityRecord) -> str:
    virtual = record.environment is Environment.VIRTUAL
    if record.sport is Sport.RIDE:
        return "VirtualRide" if virtual else "Ride"
    if record.sport is Sport.RUN:
        return "VirtualRun" if virtual else "Run"
    return record.sport.value


def _streams(streams: MergedStreams | None) -> tuple[dict[str, Any], list[str]]:
    if streams is None:
        return {}, []
    fields: dict[str, Any] = {"time": list(streams.time_s)}
    labels: list[str] = []
    for channel, key in _STREAM_KEYS:
        choice = streams.channels.get(channel)
        if choice is None:
            continue
        if channel is StreamChannel.MOVING:
            fields[key] = [_moving(value) for value in choice.values]
        else:
            fields[key] = list(choice.values)
        label = _label(choice.source.stored.detail.provenance)
        if label and label not in labels:
            labels.append(label)
    return fields, labels


def _moving(value: float | None) -> bool | float | None:
    """Map the canonical 1.0 / 0.0 moving flags to the legacy booleans."""
    if value is None:
        return None
    return _MOVING_FLAGS.get(value, value)


def _laps(laps: SetChoice | None) -> list[dict[str, float]]:
    if laps is None:
        return []
    detail = laps.chosen.stored.detail
    if not isinstance(detail, ActivityLapSet):
        raise TypeError("analysis laps must come from a lap set")
    return [
        {"start_time": lap.start_offset_s, "end_time": lap.end_offset_s}
        for lap in detail.laps
    ]


def _label(provenance: Provenance) -> str:
    if provenance.label:
        return provenance.label
    return provenance.provider.value if provenance.provider is not None else ""
