"""Intervals.icu event fields that a synced remote workout carries back."""

from __future__ import annotations

# Planned-unit metrics a synced remote event carries back onto the local unit.
REMOTE_EVENT_METRIC_KEYS = (
    "moving_time",
    "workout_doc",
    "icu_training_load",
    "icu_intensity",
)
