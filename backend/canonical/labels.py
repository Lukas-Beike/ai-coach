"""German display labels for canonical vocabulary members."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from backend.canonical.vocabulary import Sport

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


def sport_label_de(sport: Sport | str) -> str:
    """Return the German label for a sport; unknown values raise ValueError."""
    return SPORT_LABELS_DE[Sport(sport)]
