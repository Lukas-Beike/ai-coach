"""German display labels for canonical vocabulary members."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from backend.canonical.vocabulary import ActivityPurpose, ProviderId, Sport

# Provider names as user-facing error messages spell them.
PROVIDER_ERROR_LABELS: Final[Mapping[str, str]] = {
    ProviderId.GARMIN.value: "Garmin",
    ProviderId.INTERVALS.value: "Intervals.icu",
}

# Short provider names a source column shows beside a value.
PROVIDER_SHORT_LABELS: Final[Mapping[ProviderId, str]] = {
    ProviderId.GARMIN: "Garmin",
    ProviderId.WAHOO: "Wahoo",
    ProviderId.INTERVALS: "Intervals.icu",
}

SPORT_LABELS_DE: Final[Mapping[Sport, str]] = {
    Sport.RIDE: "Radfahren",
    Sport.RUN: "Laufen",
    Sport.SWIM: "Schwimmen",
    Sport.WALK: "Gehen",
    Sport.HIKE: "Wandern",
    Sport.STRENGTH: "Krafttraining",
    Sport.ROW: "Rudern",
    Sport.NORDIC_SKI: "Langlauf",
    Sport.ALPINE_SKI: "Alpinski",
    Sport.YOGA: "Yoga",
    Sport.OTHER: "Sonstiges",
}

PURPOSE_LABELS_DE: Final[Mapping[ActivityPurpose, str]] = {
    ActivityPurpose.TRAINING: "Training",
    ActivityPurpose.RACE: "Wettkampf",
    ActivityPurpose.COMMUTE: "Pendeln",
    ActivityPurpose.WARMUP: "Einfahren",
    ActivityPurpose.COOLDOWN: "Ausfahren",
}


def sport_label_de(sport: Sport | str) -> str:
    """Return the German label for a sport; unknown values raise ValueError."""
    return SPORT_LABELS_DE[Sport(sport)]
