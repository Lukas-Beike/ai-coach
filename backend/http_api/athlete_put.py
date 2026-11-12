"""Authenticated local athlete PUT routes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from time import monotonic
from typing import Any

from backend.athlete.profile import ProfileService
from backend.errors import NOT_FOUND_ERROR, AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class AthletePutRoutes:
    """Dispatch athlete writes through their existing domain services."""

    def __init__(
        self,
        profile_service: Callable[[], ProfileService],
        database_lock: Any | None = None,
        zone_service: Callable[[], Any] | None = None,
        body_export: Callable[[dict[str, str], str | None, float], str] | None = None,
    ) -> None:
        self._profile_service = profile_service
        self._database_lock = database_lock
        self._zone_service = zone_service
        self._body_export = body_export

    def routes(self) -> list[Route]:
        routes = [
            Route("PUT", "/api/profile", Access.SESSION_CSRF, self._handle_profile)
        ]
        if self._zone_service is not None:
            routes += [
                Route("PUT", "/api/zones", Access.SESSION_CSRF, self._save_zones),
                Route(
                    "PUT", "/api/zones/remove", Access.SESSION_CSRF, self._remove_zones
                ),
            ]
        return routes

    def _handle_profile(self, handler: Any, _request: RouteRequest) -> None:
        """Patch only the submitted profile fields.

        Request: JSON object of profile fields; fields not sent keep their value,
        unknown keys are ignored, `null` clears a field, values are trimmed to 4000
        characters. Fields: `name`, `goals`, `sports`, `training_background`,
        `typical_weekly_volume`, `availability`, `constraints`, `equipment`,
        `training_preferences` and its `_running`, `_cycling`, `_swimming`,
        `_strength`, `_mobility` variants, `training_model` (`pyramidal`,
        `polarized`, `threshold`, `sweet_spot`), `performance_notes`, `weight_kg`
        (20 to 300), `body_fat_pct` (1 to 70), `height_cm` (50 to 250), `sex`
        (`male`, `female` or empty), `coaching_style`, `timezone` (IANA name),
        `weather_location`, `sleep_target_hours` (4 to 12), `fueling_tolerance`,
        `first_threshold_pct` (40 to 100, percent of the run threshold HR),
        `first_threshold_origin` (`measured`, `estimated` or empty) and
        `preferred_source_thresholds`, `_body`, `_hrv`, `_resting_hr`, `_sleep`
        (`garmin` or empty). Instead of the percent, `first_threshold_hr` (bpm, 60
        to 220) with optional `first_threshold_on` (`YYYY-MM-DD`) is converted with
        the run threshold HR of that day and stored as `measured`. With
        `sync_body_to_garmin: true` a changed `weight_kg` or `body_fat_pct` is also
        exported to Garmin; with `retry_body_to_garmin: true` as well, the export
        runs even when unchanged. Neither flag is stored.

        Response: 200 with the saved profile (every field as a string); with
        `sync_body_to_garmin: true` also `garmin_body_export`: `unchanged`,
        `success`, `uncertain`, `rejected`, `unavailable`, `superseded` or
        `invalid`. The profile is saved before the export, whatever its outcome.

        Errors: 400 "Die Zeitzone muss eine gültige IANA-Zeitzone sein."; 400
        "Unbekanntes Trainingsmodell; erlaubt: pyramidal, polarized, threshold,
        sweet_spot"; 400 "Unbekannte bevorzugte Quelle; erlaubt: garmin oder leer.";
        400 "Unbekanntes Geschlecht; erlaubt: male, female oder leer."; 400 "Das
        Gewicht muss zwischen 20 und 300 kg liegen.", "Die Größe muss zwischen 50
        und 250 cm liegen.", "Der Körperfettanteil muss zwischen 1 und 70 %
        liegen.", "Das Schlafziel muss zwischen 4 und 12 Stunden liegen."; 400
        "Die Herkunft der ersten Schwelle muss gemessen oder geschätzt sein."; 400
        "Die gemessene erste Schwelle muss zwischen 40 und 100 % LSHF liegen."; 400
        "Die gemessene erste Schwelle muss zwischen 60 und 220 bpm liegen."; 400
        "Das Messdatum muss das Format JJJJ-MM-TT haben."; 400 "Zu diesem Datum ist
        keine Laktatschwelle (LSHF) bekannt, mit der die erste Schwelle in Prozent
        gespeichert werden kann.".
        """
        deadline = monotonic() + 10.0
        payload = handler.read_json()
        profile = self._profile_service()
        opted_in = (
            isinstance(payload, dict) and payload.get("sync_body_to_garmin") is True
        )
        retry_export = opted_in and payload.get("retry_body_to_garmin") is True
        changes = (
            {
                k: v
                for k, v in payload.items()
                if k not in {"sync_body_to_garmin", "retry_body_to_garmin"}
            }
            if isinstance(payload, dict)
            else payload
        )
        with profile.mutation_coordinator, self._database_lock or nullcontext():
            before = profile.get() if opted_in and self._body_export else None
            result = profile.patch(changes)
            revision = profile.revision() if before is not None else None

        result = self._export_body_if_needed(
            result, before, retry_export, revision, deadline
        )
        handler.send_json(200, result)

    def _export_body_if_needed(
        self,
        result: dict[str, Any],
        before: dict[str, str] | None,
        retry_export: bool,
        revision: str | None,
        deadline: float,
    ) -> dict[str, Any]:
        if before is None:
            return result
        if not self._body_export:
            return {**result, "garmin_body_export": "unchanged"}
        body_changed = any(
            before.get(k) != result.get(k) for k in ("weight_kg", "body_fat_pct")
        )
        if not (retry_export or body_changed):
            return {**result, "garmin_body_export": "unchanged"}
        try:
            status = self._body_export(result, revision, deadline)
        except Exception:  # noqa: BLE001 - local profile was already committed
            status = "uncertain"
        return {**result, "garmin_body_export": status}

    def _save_zones(self, handler: Any, request: RouteRequest) -> None:
        """Save one local zone configuration.

        Request: JSON body `{"sport": string, "metric": string, "environment":
        string | null, "limits": number[], "percent_limits": number[],
        "threshold": number, "maximum": number, "valid_from": string,
        "from_beginning": boolean}`. `sport` is `ride`, `run` or `swim`; `metric`
        is `heart_rate`, `power` or `pace`; `environment` is `null` or `indoor`.
        Exactly one of `limits` (absolute upper zone limits in bpm, W or m/s) and
        `percent_limits` (percent of the threshold) is required, each 3 to 7
        numbers. `threshold` is required for `heart_rate` and `power`; `maximum` is
        read for `heart_rate` only. `valid_from` (`YYYY-MM-DD`, not in the future)
        defaults to today; `from_beginning: true` stores an undated base value
        instead.

        Response: 200 `{"configuration": object, "change": object | null}`;
        `change` is the undo reference (`id`, `entity_type`, `action`,
        `after_hash`).

        Errors: 400 "Die Zonen sind ungültig: {reason}." with the invalid field or
        rule (`sport`, `metric`, `environment`, `limits oder percent_limits`,
        `{field} braucht 3 bis 7 Werte`, `threshold`, `maximum`, `Schwellenpuls
        (LSHF) fehlt`, `FTP fehlt`, `valid_from`); 400 "Die maximale Herzfrequenz darf nicht unter dem
        Schwellenpuls liegen."; 400 "Die Zonenobergrenzen dürfen nicht über der
        maximalen Herzfrequenz liegen."; 400 "Das Datum „Gilt ab“ darf nicht in der
        Zukunft liegen.".

        The route exists only where zone editing is configured.
        """
        self._handle_zones(handler, request)

    def _remove_zones(self, handler: Any, request: RouteRequest) -> None:
        """Remove one local zone configuration.

        Request: JSON body `{"key": string, "confirmed": true}`; `key` is the `key`
        of a local configuration from `GET /api/zones`.

        Response: 200 `{"configuration": null, "change": object | null}`; `change`
        is the undo reference (`id`, `entity_type`, `action`, `after_hash`).

        Errors: 400 "Das Entfernen lokaler Zonen muss bestätigt werden." unless
        `confirmed` is `true`; 404 "Lokale Zonen nicht gefunden.".

        The route exists only where zone editing is configured.
        """
        self._handle_zones(handler, request)

    def _handle_zones(self, handler: Any, request: RouteRequest) -> None:
        if self._zone_service is None:
            raise AppError(404, NOT_FOUND_ERROR)
        payload = handler.read_json()
        with self._database_lock or nullcontext():
            service = self._zone_service()
            result = (
                service.save(payload)
                if request.path == "/api/zones"
                else service.remove(payload)
            )
        handler.send_json(200, result)
