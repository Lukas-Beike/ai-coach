"""Local training fueling suggestions and explicitly confirmed plans, never intake."""

import hashlib
import json
import math
from collections.abc import Callable
from typing import Any

from backend.errors import AppError


def unit_fingerprint(unit: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                key: unit.get(key)
                for key in (
                    "id",
                    "date",
                    "type",
                    "sport",
                    "description",
                    "duration_minutes",
                    "moving_time",
                    "target",
                    "icu_training_load",
                )
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


class FuelingService:
    def __init__(
        self,
        manager: Any,
        read_units: Callable[[], list[dict[str, Any]]],
        read_templates: Callable[[], list[dict[str, Any]]],
        read_profile: Callable[[], dict[str, Any]],
        utc_now: Callable[[], str],
    ):
        self._manager, self._read_units, self._read_templates = (
            manager,
            read_units,
            read_templates,
        )
        self._read_profile, self._utc_now = read_profile, utc_now

    def choices(self) -> dict[str, Any]:
        return {
            "units": [
                {"id": unit["id"], "name": unit.get("name"), "date": unit.get("date")}
                for unit in self._read_units()
                if unit.get("id")
                and str(unit.get("type") or unit.get("sport"))
                in {"Ride", "VirtualRide", "Run", "VirtualRun", "Cycling", "Running"}
            ]
        }

    def _unit(self, unit_id: Any) -> dict[str, Any]:
        unit = next(
            (row for row in self._read_units() if str(row.get("id")) == str(unit_id)),
            None,
        )
        if unit is None or str(unit.get("type") or unit.get("sport")) not in {
            "Ride",
            "VirtualRide",
            "Run",
            "VirtualRun",
            "Cycling",
            "Running",
        }:
            raise AppError(404, "Diese lokale Ausdauereinheit ist nicht verfügbar.")
        return unit

    def read(self, unit_id: Any) -> dict[str, Any]:
        unit = self._unit(unit_id)
        duration = unit.get("duration_minutes")
        if duration is None and unit.get("moving_time") is not None:
            duration = float(unit["moving_time"]) / 60
        hours = (
            float(duration) / 60
            if isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(duration)
            and duration > 0
            else None
        )
        known = hours is not None
        carbs = _carb_range(hours)
        templates = [
            {
                key: row.get(key)
                for key in (
                    "id",
                    "name",
                    "carbs_g",
                    "protein_g",
                    "fat_g",
                    "kcal",
                    "nutrition_basis",
                )
            }
            for row in self._read_templates()[:50]
        ]
        with self._manager.unit_of_work() as db:
            row = db.execute(
                "SELECT value FROM kv WHERE key=?", ("fueling:" + str(unit["id"]),)
            ).fetchone()
        saved = json.loads(row["value"]) if row else None
        fingerprint = unit_fingerprint(unit)
        return {
            "planned_unit_id": unit["id"],
            "unit_sha256": fingerprint,
            "name": unit.get("name"),
            "date": unit.get("date"),
            "duration_hours": hours,
            "status": "suggestion" if known else "insufficient_data",
            "carbs_g_per_hour": carbs,
            "fluid_ml_per_hour": [400, 800] if known else None,
            "templates": templates,
            "tolerance": self._read_profile().get("fueling_tolerance")
            or "Nicht bestätigt; hohe Kohlenhydratmengen nicht ungeprüft übernehmen.",
            "timeline": [
                "Vorher: vertraute, verträgliche kohlenhydratreiche Mahlzeit mit ausreichend Abstand zur Einheit.",
                "Während: Kohlenhydrate und Flüssigkeit regelmäßig in kleinen Portionen, nach Verträglichkeit und tatsächlichen Bedingungen.",
                "Danach: normale Mahlzeit mit Kohlenhydraten und Protein; keine automatische Verzehrerfassung.",
            ],
            "method": "duration-based-general-endurance-guidance-v1",
            "basis": "General endurance starting ranges: optional carbohydrate for <=1h, 30–60 g/h for 1–2.5h, 60–90 g/h for longer sessions only if practiced; broad fluid starting range, not a measured sweat rate. No exact glycogen or sodium estimate. Intensity, heat and tolerance require individual adjustment.",
            "saved_plan": saved,
            "saved_stale": bool(saved and saved["unit_sha256"] != fingerprint),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {
            "planned_unit_id",
            "unit_sha256",
            "carbs_g_per_hour",
            "fluid_ml_per_hour",
            "template_id",
            "notes",
        }:
            raise AppError(400, "Ungültiger Verpflegungsplan.")
        current = self.read(payload.get("planned_unit_id"))
        if (
            current["status"] != "suggestion"
            or payload.get("unit_sha256") != current["unit_sha256"]
        ):
            raise AppError(
                409,
                "Einheit geändert oder Dauer unbekannt; neue Vorschau erforderlich.",
            )
        for field, limit in (("carbs_g_per_hour", 120), ("fluid_ml_per_hour", 1500)):
            value = payload.get(field)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= limit
            ):
                raise AppError(400, "Bestätigte Verpflegungsmengen sind ungültig.")
        template = next(
            (
                row
                for row in current["templates"]
                if row["id"] == payload.get("template_id")
            ),
            None,
        )
        if payload.get("template_id") and not template:
            raise AppError(404, "Die Mahlzeitvorlage ist nicht mehr vorhanden.")
        portions = None
        if (
            template
            and type(template.get("carbs_g")) in {int, float}
            and template["carbs_g"] > 0
        ):
            portions = round(
                payload["carbs_g_per_hour"]
                * current["duration_hours"]
                / template["carbs_g"],
                2,
            )
        saved = {
            "planned_unit_id": current["planned_unit_id"],
            "unit_sha256": current["unit_sha256"],
            "carbs_g_per_hour": payload["carbs_g_per_hour"],
            "fluid_ml_per_hour": payload["fluid_ml_per_hour"],
            "notes": str(payload.get("notes") or "")[:1000],
            "template_snapshot": template,
            "suggested_portions_during": portions,
            "observed_at": self._utc_now(),
            "source": "athlete-confirmed local fueling plan",
        }
        with self._manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (
                    "fueling:" + str(current["planned_unit_id"]),
                    json.dumps(saved, allow_nan=False),
                    saved["observed_at"],
                ),
            )
        return {
            "ok": True,
            "stored_locally": True,
            "consumption_logged": False,
            "fueling_plan": saved,
        }


def _carb_range(hours: float | None) -> list[int] | None:
    if hours is None:
        return None
    if hours <= 1:
        return [0, 30]
    if hours <= 2.5:
        return [30, 60]
    return [60, 90]
