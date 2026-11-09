"""The athlete's first threshold estimate (DFA-a1) and its explicit adoption.

The estimate is derived from the stored per-session results of chest-strap RR
intervals; it is never written to the profile on its own. The athlete adopts it
with an explicit action, which stores it as percent of the run threshold HR with
the origin ``estimated`` through the profile save path (change history, undo).
A measured value is replaced only when that request says so. The Coach reads the
estimate but has no tool that adopts it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_FIELD,
    ORIGIN_ESTIMATED,
    ORIGIN_MEASURED,
    first_threshold_origin,
    first_threshold_percent,
)
from backend.canonical.vocabulary import Sport
from backend.db import activity_detail_store
from backend.errors import AppError
from backend.performance.first_threshold_estimate import (
    ESTIMATE_DAYS,
    FirstThresholdEstimate,
    SessionThreshold,
    estimate_view,
    first_threshold_estimate,
)

type LthrResolver = Callable[[date | None], float | None]


class FirstThresholdService:
    """Read the athlete-level estimate and adopt it on the athlete's request."""

    def __init__(
        self,
        manager: Any,
        profile_service: Any,
        lthr_resolver: Callable[[], LthrResolver],
        today: Callable[[], date],
    ) -> None:
        self._manager = manager
        self._profile_service = profile_service
        self._lthr_resolver = lthr_resolver
        self._today = today

    def _estimate(self) -> tuple[FirstThresholdEstimate | None, LthrResolver]:
        today = self._today()
        with self._manager.reader() as db:
            rows = activity_detail_store.first_threshold_results(
                db,
                since=today - timedelta(days=ESTIMATE_DAYS - 1),
                until=today,
                sport=Sport.RUN,
            )
        resolver = self._lthr_resolver()
        sessions = [
            SessionThreshold(row.day, row.result.estimate_bpm, row.result.quality)
            for row in rows
        ]
        return (
            first_threshold_estimate(sessions, lambda day: resolver(day), today),
            resolver,
        )

    def estimate(self) -> dict[str, Any] | None:
        """The estimate as shown to the athlete and the Coach, or None."""
        estimate, resolver = self._estimate()
        return estimate_view(estimate, resolver(None))

    def adopt(self, payload: object) -> dict[str, Any]:
        """Store the shown estimate as the first threshold, with the origin estimated."""
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        estimate, resolver = self._estimate()
        if estimate is None:
            raise AppError(409, "Es liegt keine Schätzung der ersten Schwelle vor.")
        if (
            first_threshold_percent(payload.get("percent_lthr"))
            != estimate.percent_lthr
        ):
            raise AppError(
                409, "Die Schätzung hat sich geändert. Bitte die Anzeige aktualisieren."
            )
        profile = self._profile_service.get()
        origin = first_threshold_origin(profile)
        view = estimate_view(estimate, resolver(None))
        if (
            origin == ORIGIN_ESTIMATED
            and first_threshold_percent(profile.get(FIRST_THRESHOLD_FIELD))
            == estimate.percent_lthr
        ):
            # Already stored: no profile write and no history entry.
            return {
                "profile": profile,
                "first_threshold_estimate": view,
                "adopted": False,
            }
        if origin == ORIGIN_MEASURED and payload.get("replace_measured") is not True:
            raise AppError(
                409,
                "Ein gemessener Wert ist gespeichert. Zum Ersetzen bitte bestätigen.",
            )
        saved = self._profile_service.set_first_threshold(
            f"{estimate.percent_lthr:g}", ORIGIN_ESTIMATED
        )
        return {"profile": saved, "first_threshold_estimate": view, "adopted": True}
