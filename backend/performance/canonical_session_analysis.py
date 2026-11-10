"""The one canonical session analysis of a session (#1685).

Pure computation shared by the stored analysis (``SessionAnalysisStage``), the
activity detail document, the Coach detail tool, the calendar and the training
report. Its input is the session's Garmin, Wahoo and local records with their
merged detail sets; Intervals.icu records and detail sets are never read
(athlete decision 2026-11-07, epic #1732). Thresholds come from the local
resolver at the session date, never from a provider activity. No I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from backend.activities import stream_zones
from backend.activities.detail_contract import measured_order
from backend.activities.detail_merge import (
    MergedDetail,
    MergedStreams,
    channel_sources,
)
from backend.activities.workout_profile import recorded_profile
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import ActivityRecord, fingerprint_inputs
from backend.canonical.vocabulary import (
    HeartRateSource,
    ProviderId,
    StreamChannel,
    StreamResolution,
)
from backend.performance import form_drift as form_drift_module
from backend.performance import power_profile as power_profile_module
from backend.performance.analysis_input import analysis_input
from backend.performance.form_drift import form_drift
from backend.performance.power_profile import power_profile, running_profile
from backend.performance.session_analysis import (
    HEART_RATE_HISTOGRAM_VERSION,
    aerobic_analysis,
    heart_rate_histogram,
    interval_quality,
)
from backend.performance.session_execution import session_execution

# Stored ``activity_detail_analysis.analysis_version`` of canonical analyses.
ANALYSIS_VERSION: Final = 3
# Bump when the computation below changes, so the stage recomputes every row.
# v3: grade-adjusted Pa:HR of outdoor runs (#1770).
# v4: the heart rate and power source, and the optical heart rate warning (#1869).
# v5: the running form drift of long runs (#1870).
# v6: the calendar profile uses the thresholds of the zone times (#1892).
# The stored heart-rate histogram has its own version in the fingerprint.
METHOD_VERSION: Final = 6


def analysis_records(records: Iterable[ActivityRecord]) -> tuple[ActivityRecord, ...]:
    """The session records the canonical analysis reads: every non-Intervals one."""
    return tuple(
        record
        for record in records
        if record.provenance.provider is not ProviderId.INTERVALS
    )


def stream_resolution(
    streams: MergedStreams | None, *channels: StreamChannel
) -> str | None:
    """Return the resolution: downsampled when the time axis or a read channel is."""
    if streams is None:
        return None
    sources = [streams.primary] + [
        streams.channels[channel].source
        for channel in channels
        if channel in streams.channels
    ]
    downsampled = any(
        isinstance(source.stored.detail, ActivityStreamSet)
        and source.stored.detail.resolution is StreamResolution.DOWNSAMPLED
        for source in sources
    )
    return (
        StreamResolution.DOWNSAMPLED if downsampled else StreamResolution.FULL
    ).value


def session_analysis(
    records: Sequence[ActivityRecord],
    merged: MergedDetail,
    targets: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compute the session analysis from the merged streams and laps.

    ``records`` are the session's analysis records (see ``analysis_records``),
    at least one. Each analysis credits only the providers of the channels it
    reads.
    """
    ordered = measured_order(records)
    adapted = analysis_input(ordered[0], merged.streams, merged.laps, members=ordered)
    activity = adapted.activity
    hr_source, power_source = channel_sources(merged.streams)
    quality = interval_quality(
        activity,
        dict(targets) if isinstance(targets, Mapping) else None,
        source_label=adapted.label_for("watts", "heartrate", "velocity_smooth", "laps"),
    )
    if hr_source is HeartRateSource.OPTICAL and quality.get("status") in (
        "ok",
        "partial",
    ):
        quality["heart_rate_reliability"] = (
            "Optisch am Handgelenk gemessen: in Intervallen weniger zuverlässig."
        )
    result: dict[str, Any] = {
        "interval_quality": quality,
        "sensors": {
            "heart_rate": None if hr_source is None else hr_source.value,
            "power": None if power_source is None else power_source.value,
        },
        "execution": session_execution(
            activity,
            source_label=adapted.label_for(
                "watts", "heartrate", "velocity_smooth", "cadence", "laps"
            ),
        ),
        "aerobic": aerobic_analysis(
            activity,
            source_label=adapted.label_for(
                "watts",
                "heartrate",
                "velocity_smooth",
                "moving",
                "grade_smooth",
                "altitude",
                "distance",
            ),
        ),
        "power_profile": {
            **power_profile(
                activity, source_label=adapted.label_for("watts", "moving")
            ),
            "stream_resolution": stream_resolution(
                merged.streams, StreamChannel.POWER_W, StreamChannel.MOVING
            ),
        },
        "running_profile": {
            **running_profile(
                activity,
                source_label=adapted.label_for("velocity_smooth", "distance", "moving"),
            ),
            "stream_resolution": stream_resolution(
                merged.streams,
                StreamChannel.SPEED_MPS,
                StreamChannel.DISTANCE_M,
                StreamChannel.MOVING,
            ),
        },
    }
    drift = form_drift(
        activity,
        source_label=adapted.label_for(
            "velocity_smooth",
            "moving",
            "ground_contact_time",
            "vertical_oscillation",
            "step_length",
        ),
    )
    # Only non-trail runs carry the key.
    if drift is not None:
        result["form_drift"] = drift
    return result


def calendar_profile(
    records: Sequence[ActivityRecord],
    merged: MergedDetail,
    *,
    ftp_w: float | None,
    threshold_hr_bpm: float | None,
) -> dict[str, Any] | None:
    """The recorded workout profile of the calendar, from the merged streams.

    Power segments are colored against ``ftp_w``, heart-rate segments against
    ``threshold_hr_bpm``, both resolved locally for the session date.
    """
    ordered = measured_order(records)
    adapted = analysis_input(ordered[0], merged.streams, None, members=ordered)
    return recorded_profile(
        adapted.activity, ftp_w=ftp_w, threshold_hr_bpm=threshold_hr_bpm
    )


def session_heart_rate_histogram(
    records: Sequence[ActivityRecord], merged: MergedDetail
) -> dict[str, Any] | None:
    """The seconds per bpm of the merged full-resolution heart-rate stream (M6 v5)."""
    ordered = measured_order(records)
    adapted = analysis_input(ordered[0], merged.streams, None, members=ordered)
    return heart_rate_histogram(adapted.activity)


def record_part(record: ActivityRecord) -> list[object]:
    """The record fields the analysis reads, for the input fingerprint."""
    provider = record.provenance.provider
    return [
        None if provider is None else provider.value,
        record.activity_id,
        record.provenance.recorded_by.value,
        record.provenance.label,
        None if record.device_type is None else record.device_type.value,
        record.sport.value,
        record.environment.value,
        record.terrain.value,
        record.started_at.isoformat(),
    ]


def analysis_fingerprint(
    records: Sequence[ActivityRecord],
    set_hashes: Iterable[str],
    *,
    stale: bool,
    targets: Mapping[str, Any] | None,
    thresholds: Mapping[str, Any],
) -> str:
    """Fingerprint of every input of one stored session analysis.

    Covers the method versions, the analysis records, the content hashes of
    the stream and lap sets (each hash covers its mapper version), whether a
    provider detail is stale, the frozen targets and the thresholds used.
    """
    return fingerprint_inputs(
        {
            "versions": [
                ANALYSIS_VERSION,
                METHOD_VERSION,
                power_profile_module.METHOD_VERSION,
                form_drift_module.METHOD_VERSION,
                stream_zones.ZONE_TIMES_VERSION,
                HEART_RATE_HISTOGRAM_VERSION,
            ],
            "records": [record_part(record) for record in measured_order(records)],
            "sets": sorted(set_hashes),
            "stale": stale,
            "targets": None if targets is None else dict(targets),
            "thresholds": dict(thresholds),
        }
    )
