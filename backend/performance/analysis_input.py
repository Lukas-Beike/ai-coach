"""Canonical merged detail as the legacy input of the session analysis.

The analysis functions read the Intervals.icu-shaped activity dict. This pure
adapter builds that dict from merged canonical streams and laps of any
provider. It never mutates its inputs and performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.activities.detail_merge import (
    MergedStreams,
    SetChoice,
    clock_offset,
)
from backend.canonical.activity_detail import ActivityLapSet
from backend.canonical.records import (
    ActivityRecord,
    Provenance,
    session_terrain,
)
from backend.canonical.vocabulary import (
    Sport,
    StreamChannel,
    Terrain,
)

# Canonical channels and the legacy stream keys the analysis reads them from.
_STREAM_KEYS: tuple[tuple[StreamChannel, str], ...] = (
    (StreamChannel.POWER_W, "watts"),
    (StreamChannel.HEART_RATE_BPM, "heartrate"),
    (StreamChannel.SPEED_MPS, "velocity_smooth"),
    (StreamChannel.DISTANCE_M, "distance"),
    (StreamChannel.ALTITUDE_M, "altitude"),
    (StreamChannel.GRADE_PCT, "grade_smooth"),
    (StreamChannel.MOVING, "moving"),
    (StreamChannel.CADENCE_RPM, "cadence"),
    # Running dynamics, read by the form drift analysis only (#1870).
    (StreamChannel.GROUND_CONTACT_TIME_MS, "ground_contact_time"),
    (StreamChannel.VERTICAL_OSCILLATION_CM, "vertical_oscillation"),
    (StreamChannel.STEP_LENGTH_M, "step_length"),
)


_MOVING_FLAGS: dict[float, bool] = {1.0: True, 0.0: False}


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    """Legacy-shaped activity dict and the provider labels of its detail.

    ``source_label`` names every provider whose streams were mapped;
    ``channel_labels`` names the provider of each legacy stream key and of
    ``"laps"``, so an analysis can credit only the data it reads.
    """

    activity: dict[str, Any]
    source_label: str
    channel_labels: Mapping[str, str]

    def label_for(self, *keys: str) -> str:
        """Label of the providers that supplied ``keys``, else ``source_label``."""
        labels = dict.fromkeys(
            self.channel_labels[key] for key in keys if key in self.channel_labels
        )
        return " / ".join(labels) if labels else self.source_label


def analysis_input(
    record: ActivityRecord,
    streams: MergedStreams | None,
    laps: SetChoice | None,
    *,
    members: Sequence[ActivityRecord] = (),
) -> AnalysisInput:
    """Build the analysis input of one activity from its merged detail.

    ``members`` are the session's records in measured order, for its terrain.
    """
    stream_fields, channel_labels = _streams(streams)
    lap_fields = _laps(laps, streams)
    if laps is not None and lap_fields:
        lap_label = _label(laps.chosen.stored.detail.provenance)
        if lap_label:
            channel_labels["laps"] = lap_label
    labels = dict.fromkeys(
        label for key, label in channel_labels.items() if key != "laps"
    )
    activity: dict[str, Any] = {
        **analysis_sport(record, members),
        "streams": stream_fields,
        "laps": lap_fields,
    }
    if laps is not None and lap_fields:
        detail = laps.chosen.stored.detail
        if isinstance(detail, ActivityLapSet):
            activity["lap_source"] = detail.lap_source.value
    return AnalysisInput(
        activity=activity,
        source_label=" / ".join(labels) if labels else _label(record.provenance),
        channel_labels=channel_labels,
    )


def analysis_sport(
    record: ActivityRecord, members: Sequence[ActivityRecord] = ()
) -> dict[str, Any]:
    """Return the canonical sport, environment and trail-run flag.

    Sport and environment are ``record``'s. The terrain follows
    ``session_terrain`` over ``members`` (the session's records in measured
    order, as its summary reads them), else over ``record`` alone. ``trail``
    marks a trail run, whose pace the road-pace analyses leave out.
    """
    terrain = session_terrain(members or (record,))
    return {
        "sport": record.sport.value,
        "environment": record.environment.value,
        "trail": record.sport is Sport.RUN and terrain is Terrain.TRAIL,
    }


def _streams(
    streams: MergedStreams | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    if streams is None:
        return {}, {}
    fields: dict[str, Any] = {"time": list(streams.time_s)}
    labels: dict[str, str] = {}
    for channel, key in _STREAM_KEYS:
        choice = streams.channels.get(channel)
        if choice is None:
            continue
        if channel is StreamChannel.MOVING:
            fields[key] = [_moving(value) for value in choice.values]
        else:
            fields[key] = list(choice.values)
        label = _label(choice.source.stored.detail.provenance)
        if label:
            labels[key] = label
    return fields, labels


def _moving(value: float | None) -> bool | float | None:
    """Map the canonical 1.0 / 0.0 moving flags to the legacy booleans."""
    if value is None:
        return None
    return _MOVING_FLAGS.get(value, value)


def _laps(
    laps: SetChoice | None, streams: MergedStreams | None
) -> list[dict[str, Any]]:
    """Lap windows on the clock of the primary streams, or none when unalignable."""
    if laps is None:
        return []
    detail = laps.chosen.stored.detail
    if not isinstance(detail, ActivityLapSet):
        raise TypeError("analysis laps must come from a lap set")
    offset = 0.0 if streams is None else clock_offset(laps.chosen, streams.primary)
    if offset is None:
        return []
    return [
        {
            "start_time": lap.start_offset_s + offset,
            "end_time": lap.end_offset_s + offset,
            "kind": lap.kind.value,
            "distance_m": lap.distance_m,
        }
        for lap in detail.laps
    ]


def _label(provenance: Provenance) -> str:
    if provenance.label:
        return provenance.label
    return provenance.provider.value if provenance.provider is not None else ""
