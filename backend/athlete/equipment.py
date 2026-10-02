"""Explicit gear assignments and athlete-defined maintenance usage counters."""

import json
import math
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.performance.training_report import canonical_rows, number


class EquipmentService:
    def __init__(
        self,
        manager: Any,
        read_snapshot: Callable[[], dict[str, Any]],
        today: Callable[[], date],
        utc_now: Callable[[], str],
    ):
        self._manager, self._read_snapshot, self._today, self._utc_now = (
            manager,
            read_snapshot,
            today,
            utc_now,
        )

    def _records(self, db: Any, prefix: str, limit: int) -> list[dict[str, Any]]:
        return [
            json.loads(row["value"])
            for row in db.execute(
                "SELECT value FROM kv WHERE key LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (prefix + ":%", limit),
            ).fetchall()
        ]

    def read(self, item_id: str | None = None) -> dict[str, Any]:
        rows, duplicates = canonical_rows(self._read_snapshot() or {})
        with self._manager.unit_of_work() as db:
            garmin_row = db.execute(
                "SELECT value FROM kv WHERE key='garmin_snapshot'"
            ).fetchone()
            try:
                garmin = json.loads(garmin_row["value"]) if garmin_row else {}
            except (TypeError, json.JSONDecodeError):
                garmin = {}
            garmin = garmin if isinstance(garmin, dict) else {}
            items = self._records(db, "equipment", 100)
            if item_id:
                selected = db.execute(
                    "SELECT value FROM kv WHERE key=?", ("equipment:" + item_id,)
                ).fetchone()
                if not selected:
                    raise AppError(404, "Ausrüstung nicht gefunden.")
                items = [json.loads(selected["value"])]
            assignments = {
                row["activity_id"]: row
                for row in self._records(db, "equipment_assignment", 2000)
            }
            maintenance = self._records(db, "equipment_maintenance", 1000)
        for item in items:
            eligible = [
                row
                for row in rows
                if (assignments.get(str(row.get("id"))) or {}).get("equipment_id")
                == (item.get("parent_id") or item["id"])
                and item["start_date"]
                <= str(row.get("start_date_local") or "")[:10]
                <= self._today().isoformat()
            ]
            events = sorted(
                [row for row in maintenance if row["equipment_id"] == item["id"]],
                key=lambda row: (row["date"], row["observed_at"]),
            )
            latest = events[-1] if events else None
            ambiguous = [
                row
                for row in eligible
                if latest
                and str(row.get("start_date_local") or "")[:10] == latest["date"]
            ]
            since = [
                row
                for row in eligible
                if not latest
                or str(row.get("start_date_local") or "")[:10] > latest["date"]
            ]
            distance = sum(number(row.get("distance")) or 0 for row in eligible) / 1000
            hours = sum(number(row.get("moving_time")) or 0 for row in eligible) / 3600
            distance_since = sum(
                number(row.get("distance")) or 0 for row in since
            ) / 1000 + (item["initial_distance_km"] if not latest else 0)
            hours_since = sum(
                number(row.get("moving_time")) or 0 for row in since
            ) / 3600 + (item["initial_hours"] if not latest else 0)
            reached = bool(
                item.get("maintenance_km")
                and distance_since >= item["maintenance_km"]
                or item.get("maintenance_hours")
                and hours_since >= item["maintenance_hours"]
            )
            uncertain = bool(ambiguous) or any(
                item.get(interval)
                and any(number(row.get(measure)) is None for row in since)
                for interval, measure in (
                    ("maintenance_km", "distance"),
                    ("maintenance_hours", "moving_time"),
                )
            )
            item["usage"] = {
                "distance_km": round(item["initial_distance_km"] + distance, 2),
                "hours": round(item["initial_hours"] + hours, 2),
                "assigned_sessions": len(eligible),
                "distance_known_sessions": sum(
                    number(row.get("distance")) is not None for row in eligible
                ),
                "time_known_sessions": sum(
                    number(row.get("moving_time")) is not None for row in eligible
                ),
                "maintenance_distance_km": round(distance_since, 2),
                "maintenance_hours": round(hours_since, 2),
                "maintenance_due": True if reached else None if uncertain else False,
                "maintenance_same_day_sessions": len(ambiguous),
                "maintenance_coverage": "partial" if uncertain else "known_assignments",
            }
            item["maintenance"] = events
        return {
            "items": items,
            "garmin_items": self._garmin_items(garmin),
            "garmin_synced_at": garmin.get("synced_at"),
            "garmin_freshness": (garmin.get("source_freshness") or {})
            .get("gear", {})
            .get("freshness"),
            "assignments": list(assignments.values()),
            "excluded_duplicates": duplicates,
            "scope": "Known canonical snapshot activities with explicit assignments only, plus confirmed initial usage. Missing provider history or measurements makes counters incomplete; no inferred favorite gear. Maintenance includes only later calendar days, same-day order is unknown. Limits: 100 items, 2000 assignments, 1000 maintenance events.",
        }

    @staticmethod
    def _garmin_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        items = []
        for row in snapshot.get("gear") or []:
            if not isinstance(row, dict):
                continue
            stats = row.get("stats") or {}
            distance = (
                number(stats.get("totalDistance")) if isinstance(stats, dict) else None
            )
            goal = number(row.get("maximumMeters"))
            items.append(
                {
                    "id": str(row.get("gearUUID") or ""),
                    "name": str(row.get("gearName") or "Ausrüstung")[:200],
                    "kind": str(row.get("gearTypeName") or "")[:100],
                    "status": str(row.get("gearStatusName") or "")[:100],
                    "distance_km": round(distance / 1000, 2)
                    if distance is not None
                    else None,
                    "goal_km": round(goal / 1000, 2) if goal else None,
                    "usage_percent": round(distance / goal * 100, 1)
                    if distance is not None and goal
                    else None,
                    "sessions": number(stats.get("totalActivities"))
                    if isinstance(stats, dict)
                    else None,
                    "source": "Garmin Connect",
                }
            )
        return items

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "id",
            "expected_revision",
            "name",
            "sport",
            "kind",
            "status",
            "parent_id",
            "start_date",
            "initial_distance_km",
            "initial_hours",
            "maintenance_km",
            "maintenance_hours",
        }
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise AppError(400, "Ungültige Ausrüstung.")
        name = str(payload.get("name") or "").strip()
        if (
            not name
            or len(name) > 200
            or payload.get("sport")
            not in {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining"}
            or payload.get("kind") not in {"shoes", "bike", "component", "other"}
            or payload.get("status", "active") not in {"active", "archived"}
        ):
            raise AppError(400, "Name, Sport, Art oder Status der Ausrüstung ungültig.")
        try:
            start = date.fromisoformat(str(payload.get("start_date")))
            item_id = str(payload.get("id") or uuid.uuid4())
            uuid.UUID(item_id)
        except ValueError as exc:
            raise AppError(400, "Startdatum oder Ausrüstungs-ID ungültig.") from exc
        if not date(2010, 1, 1) <= start <= self._today():
            raise AppError(
                400, "Ausrüstungsbeginn liegt außerhalb des gültigen Zeitraums."
            )
        amounts = {}
        for field, maximum in (
            ("initial_distance_km", 1000000),
            ("initial_hours", 100000),
            ("maintenance_km", 1000000),
            ("maintenance_hours", 100000),
        ):
            value = payload.get(field)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= maximum
            ):
                raise AppError(
                    400, "Ausrüstungszähler oder Wartungsintervall ungültig."
                )
            if field.startswith("initial") and value is None:
                raise AppError(
                    400, "Anfangsstand muss ausdrücklich als Zahl angegeben werden."
                )
            amounts[field] = value
        with self._manager.unit_of_work() as db:
            old = db.execute(
                "SELECT value FROM kv WHERE key=?", ("equipment:" + item_id,)
            ).fetchone()
            previous = json.loads(old["value"]) if old else None
            if payload.get("id") and not previous:
                raise AppError(404, "Ausrüstung nicht gefunden.")
            if previous and payload.get("expected_revision") != previous["revision"]:
                raise AppError(409, "Ausrüstung geändert; neu lesen.")
            parent_id = payload.get("parent_id") or None
            if payload["kind"] == "component" and not parent_id:
                raise AppError(400, "Eine Komponente benötigt einen Hauptgegenstand.")
            if parent_id:
                parent = db.execute(
                    "SELECT value FROM kv WHERE key=?", ("equipment:" + str(parent_id),)
                ).fetchone()
                if (
                    payload["kind"] != "component"
                    or not parent
                    or parent_id == item_id
                    or json.loads(parent["value"]).get("parent_id")
                    or json.loads(parent["value"])["kind"] == "component"
                    or json.loads(parent["value"])["sport"] != payload["sport"]
                ):
                    raise AppError(
                        400,
                        "Komponente benötigt einen vorhandenen Hauptgegenstand ohne Elternkomponente.",
                    )
            children = [
                json.loads(row["value"])
                for row in db.execute(
                    "SELECT value FROM kv WHERE key LIKE 'equipment:%' AND json_extract(value, '$.parent_id')=?",
                    (item_id,),
                ).fetchall()
            ]
            if children and (
                parent_id
                or payload["kind"] == "component"
                or any(item["sport"] != payload["sport"] for item in children)
            ):
                raise AppError(
                    409,
                    "Vorhandene Komponenten benötigen diesen Hauptgegenstand und dessen Sportart.",
                )
            saved = {
                "id": item_id,
                "name": name,
                "sport": payload["sport"],
                "kind": payload["kind"],
                "status": payload.get("status", "active"),
                "parent_id": parent_id,
                "start_date": start.isoformat(),
                **amounts,
                "revision": previous["revision"] + 1 if previous else 1,
                "updated_at": self._utc_now(),
                "source": "athlete-entered equipment",
            }
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (
                    "equipment:" + item_id,
                    json.dumps(saved, allow_nan=False),
                    saved["updated_at"],
                ),
            )
        return {"ok": True, "stored_locally": True, "equipment": saved}

    def assign(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {
            "activity_id",
            "equipment_id",
        }:
            raise AppError(400, "Aktivität und Ausrüstung sind erforderlich.")
        rows, _ = canonical_rows(self._read_snapshot() or {})
        row = next(
            (row for row in rows if str(row.get("id")) == str(payload["activity_id"])),
            None,
        )
        if row is None:
            raise AppError(404, "Kanonische Aktivität nicht gefunden.")
        with self._manager.unit_of_work() as db:
            item = db.execute(
                "SELECT value FROM kv WHERE key=?",
                ("equipment:" + str(payload["equipment_id"]),),
            ).fetchone()
            equipment = json.loads(item["value"]) if item else None
            if payload["equipment_id"] is not None and (
                not equipment
                or equipment["status"] != "active"
                or equipment.get("parent_id")
                or equipment["sport"] != row.get("type")
            ):
                raise AppError(400, "Aktive passende Hauptausrüstung erforderlich.")
            saved = {
                "activity_id": str(row["id"]),
                "equipment_id": equipment["id"] if equipment else None,
                "observed_at": self._utc_now(),
            }
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (
                    "equipment_assignment:" + str(row["id"]),
                    json.dumps(saved),
                    saved["observed_at"],
                ),
            )
        return {"ok": True, "stored_locally": True, "assignment": saved}

    def maintain(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {
            "equipment_id",
            "date",
            "notes",
        }:
            raise AppError(400, "Ungültige Wartung.")
        try:
            day = date.fromisoformat(str(payload.get("date")))
        except ValueError as exc:
            raise AppError(400, "Wartungsdatum ungültig.") from exc
        item = next(
            (
                item
                for item in self.read(str(payload.get("equipment_id") or ""))["items"]
                if item["id"] == payload.get("equipment_id")
            ),
            None,
        )
        if (
            not item
            or not date.fromisoformat(item["start_date"]) <= day <= self._today()
        ):
            raise AppError(400, "Wartungsgegenstand oder Datum ungültig.")
        saved = {
            "id": str(uuid.uuid4()),
            "equipment_id": item["id"],
            "date": day.isoformat(),
            "notes": str(payload.get("notes") or "")[:1000],
            "observed_at": self._utc_now(),
        }
        with self._manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (
                    "equipment_maintenance:" + saved["id"],
                    json.dumps(saved),
                    saved["observed_at"],
                ),
            )
        return {"ok": True, "stored_locally": True, "maintenance": saved}
