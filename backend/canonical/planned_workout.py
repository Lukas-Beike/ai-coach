"""Provider-neutral export values for one planned workout."""

from __future__ import annotations

from dataclasses import dataclass

from backend.canonical.vocabulary import Environment, Sport


@dataclass(frozen=True, slots=True)
class PlannedWorkoutExport:
    """One planned workout after local validation, free of provider names.

    ``sport_token`` is the stored sport text as a string (empty when none was
    stored). Only a provider adapter may map it onto its own activity type:
    ``Sport`` is coarser than
    provider types (EBikeRide and Ride are both ``Sport.RIDE``), so the exact
    provider type cannot be recovered from ``sport`` alone.
    """

    starts_at_local: str
    sport: Sport
    environment: Environment
    sport_token: str
    name: str
    description: str
    duration_seconds: int
    target: str
