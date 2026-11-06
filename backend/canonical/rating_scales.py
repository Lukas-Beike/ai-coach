"""Scales of the subjective ratings an athlete enters, locally or in a provider.

A rating is stored as entered; its scale is fixed by where it was entered, so it
is resolved at read time. Consumers get the raw value with its scale, direction
and label, or a normalized value with one direction: 0 is the best or lowest
strain, 1 the worst or highest strain.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal

from backend.canonical.vocabulary import MetricKind

HigherIs = Literal["better", "worse", "harder"]

_DIRECTION_TEXT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "better": "höher = besser",
        "worse": "höher = schlechter",
        "harder": "höher = härter",
    }
)


@dataclass(frozen=True, slots=True)
class RatingScale:
    """The integer range, direction and labels of one rating scale."""

    scale_id: str
    minimum: int
    maximum: int
    higher_is: HigherIs
    labels: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.maximum <= self.minimum:
            raise ValueError("maximum must be above minimum")
        if self.higher_is not in _DIRECTION_TEXT:
            raise ValueError("unknown rating direction")
        if any(not self.minimum <= key <= self.maximum for key in self.labels):
            raise ValueError("label outside the scale")
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))

    def normalized(self, value: float) -> float:
        """Return ``value`` on 0..1, 0 = best or lowest strain, 1 = worst or highest."""
        if not self.minimum <= value <= self.maximum:
            raise ValueError("value outside the scale")
        share = (value - self.minimum) / (self.maximum - self.minimum)
        return 1.0 - share if self.higher_is == "better" else share

    def label(self, value: float) -> str | None:
        """Return the label of an integral ``value``, if the scale names it."""
        return self.labels.get(int(value)) if float(value).is_integer() else None

    def describe(self) -> str:
        """Return the range, direction and end labels, e.g. ``1–5, höher = schlechter``."""
        text = f"{self.minimum}–{self.maximum}, {_DIRECTION_TEXT[self.higher_is]}"
        low, high = self.labels.get(self.minimum), self.labels.get(self.maximum)
        if low is None or high is None:
            return text
        return f"{text} ({self.minimum} {low} … {self.maximum} {high})"


_STRAIN_LABELS: Final = {1: "niedrig", 2: "mittel", 3: "hoch", 4: "extrem"}

# Intervals.icu wellness ratings run 1..4, 1 good and 4 bad, mood included.
INTERVALS_WELLNESS_SCALES: Final[Mapping[MetricKind, RatingScale]] = MappingProxyType(
    {
        MetricKind.SUBJECTIVE_FATIGUE: RatingScale(
            "intervals_fatigue_1_4", 1, 4, "worse", _STRAIN_LABELS
        ),
        MetricKind.SUBJECTIVE_SORENESS: RatingScale(
            "intervals_soreness_1_4", 1, 4, "worse", _STRAIN_LABELS
        ),
        MetricKind.SUBJECTIVE_STRESS: RatingScale(
            "intervals_stress_1_4", 1, 4, "worse", _STRAIN_LABELS
        ),
        MetricKind.SUBJECTIVE_MOOD: RatingScale(
            "intervals_mood_1_4",
            1,
            4,
            "worse",
            {1: "super", 2: "gut", 3: "okay", 4: "mies"},
        ),
    }
)
# Intervals.icu activity feel runs 1 strong .. 5 weak; its RPE runs 1..10.
INTERVALS_FEEL_SCALE: Final = RatingScale(
    "intervals_feel_1_5",
    1,
    5,
    "worse",
    {1: "stark", 2: "gut", 3: "normal", 4: "schlecht", 5: "schwach"},
)
INTERVALS_RPE_SCALE: Final = RatingScale(
    "intervals_rpe_1_10", 1, 10, "harder", {1: "sehr leicht", 10: "maximal"}
)
# The app's daily check-in and activity feedback ratings run 0..10.
LOCAL_SESSION_RPE_SCALE: Final = RatingScale(
    "local_rpe_0_10", 0, 10, "harder", {0: "Ruhe", 10: "maximal"}
)
LOCAL_CHECKIN_SCALES: Final[Mapping[str, RatingScale]] = MappingProxyType(
    {
        "soreness": RatingScale("local_soreness_0_10", 0, 10, "worse"),
        "stress": RatingScale("local_stress_0_10", 0, 10, "worse"),
        "motivation": RatingScale("local_motivation_0_10", 0, 10, "better"),
        "session_rpe": LOCAL_SESSION_RPE_SCALE,
    }
)
