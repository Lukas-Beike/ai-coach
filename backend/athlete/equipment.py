"""Explicit gear assignments and athlete-defined maintenance usage counters."""

import json
import math
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.performance.training_report import canonical_rows, number

EQUIPMENT_PREFIX = "equipment:"
SELECT_VALUE = "SELECT value FROM kv WHERE key=?"


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
            if garmin.get("source") == "fixture":
                garmin = {key: value for key, value in garmin.items() if key != "gear"}
            gear_initialized = (
                db.execute(SELECT_VALUE, ("garmin_equipment_initialized",)).fetchone()
                is not None
            )
            garmin_usage = {
                str(row.get("gearUUID")): _garmin_distance_km(row)
                for row in garmin.get("gear") or []
                if isinstance(row, dict) and row.get("gearUUID")
            }
            items = self._records(db, "equipment", 100)
            if item_id:
                selected = db.execute(
                    SELECT_VALUE, (EQUIPMENT_PREFIX + item_id,)
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
            _update_usage(
                item, rows, assignments, maintenance, self._today(), garmin_usage
            )
        return {
            "items": items,
            "garmin_items": []
            if gear_initialized
            else [
                item
                for item in self._garmin_items(garmin)
                if item["id"] not in {str(local.get("garmin_uuid")) for local in items}
            ],
            "garmin_synced_at": garmin.get("synced_at"),
            "garmin_freshness": (garmin.get("source_freshness") or {})
            .get("gear", {})
            .get("freshness"),
            "assignments": list(assignments.values()),
            "excluded_duplicates": duplicates,
            "scope": "Known canonical snapshot activities with explicit assignments only, plus confirmed initial usage. Missing provider history or measurements makes counters incomplete; no inferred favorite gear. Maintenance includes only later calendar days, same-day order is unknown. Limits: 100 items, 2000 assignments, 1000 maintenance events.",
        }

    def sync_garmin_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Import Garmin gear once, then refresh only Garmin-owned mileage."""
        if not _current_garmin_gear(snapshot):
            return
        rows = [row for row in snapshot.get("gear") or [] if isinstance(row, dict)]
        rows = [row for row in rows if row.get("gearUUID")]
        # A current but empty or malformed inventory is not proof that the
        # initial import succeeded. Leave initialization open for recovery.
        if not rows:
            return
        with self._manager.unit_of_work() as db:
            initialized = db.execute(
                SELECT_VALUE, ("garmin_equipment_initialized",)
            ).fetchone()
            local_rows = [
                json.loads(row["value"])
                for row in db.execute(
                    "SELECT value FROM kv WHERE key LIKE ?", (EQUIPMENT_PREFIX + "%",)
                ).fetchall()
                if row["value"] and isinstance(json.loads(row["value"]), dict)
            ]
            by_garmin = {
                str(item["garmin_uuid"]): item
                for item in local_rows
                if item.get("garmin_uuid")
            }
            now = self._utc_now()
            # Legacy builds marked an empty first sync as initialized. A marker
            # with no linked local Garmin rows is the bounded recovery case;
            # once any rows are linked, later syncs remain mileage-only.
            initial_import = not initialized or not by_garmin
            if initial_import:
                for row in rows:
                    gear_id = str(row.get("gearUUID") or "")
                    if gear_id and gear_id not in by_garmin:
                        _insert_initial_garmin_item(
                            db, row, gear_id, self._today(), now
                        )
            _refresh_garmin_distances(db, rows, by_garmin, now)
            if not initialized:
                db.execute(
                    "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                    ("garmin_equipment_initialized", "1", now),
                )

    @staticmethod
    def _garmin_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            _garmin_item(row)
            for row in snapshot.get("gear") or []
            if isinstance(row, dict)
        ]

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
            "lifetime_target_km",
        }
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise AppError(400, "Ungültige Ausrüstung.")
        name, start, item_id = _equipment_identity(payload, self._today())
        amounts = _equipment_amounts(payload)
        with self._manager.unit_of_work() as db:
            old = db.execute(SELECT_VALUE, (EQUIPMENT_PREFIX + item_id,)).fetchone()
            previous = json.loads(old["value"]) if old else None
            if payload.get("id") and not previous:
                raise AppError(404, "Ausrüstung nicht gefunden.")
            if previous and payload.get("expected_revision") != previous["revision"]:
                raise AppError(409, "Ausrüstung geändert; neu lesen.")
            parent_id = _equipment_parent(db, payload, item_id)
            _validate_equipment_children(db, item_id, parent_id, payload)
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
                "sport_pending": payload["sport"] == "Other",
                "parent_pending": payload["kind"] == "component" and not parent_id,
            }
            _preserve_equipment_metadata(saved, previous, payload)
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (
                    EQUIPMENT_PREFIX + item_id,
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
                SELECT_VALUE,
                (EQUIPMENT_PREFIX + str(payload["equipment_id"]),),
            ).fetchone()
            equipment = json.loads(item["value"]) if item else None
            if payload["equipment_id"] is not None and (
                not equipment
                or equipment["status"] != "active"
                or equipment.get("parent_id")
                or equipment.get("parent_pending")
                or equipment.get("sport_pending")
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
            "distance_km": (
                None
                if item.get("garmin_uuid") and day < self._today()
                else item.get("usage", {}).get("distance_km")
            ),
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


def _current_garmin_gear(snapshot: Any) -> bool:
    return bool(
        isinstance(snapshot, dict)
        and (snapshot.get("source_freshness") or {}).get("gear", {}).get("freshness")
        == "current"
    )


def _insert_initial_garmin_item(
    db: Any, row: dict[str, Any], gear_id: str, today: date, now: str
) -> None:
    distance = _garmin_distance_km(row)
    kind = _garmin_kind(row)
    sport = _garmin_sport(row)
    item_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "garmin:" + gear_id))
    item = {
        "id": item_id,
        "name": str(row.get("gearName") or "Ausr\u00fcstung")[:200],
        "sport": sport,
        "sport_pending": sport == "Other",
        "kind": kind,
        "parent_pending": kind == "component",
        "status": _garmin_status(row),
        "garmin_status": _garmin_raw_status(row),
        "parent_id": None,
        "start_date": today.isoformat(),
        "initial_distance_km": distance or 0,
        "initial_hours": 0,
        "maintenance_km": None,
        "maintenance_hours": None,
        "garmin_uuid": gear_id,
        "initial_distance_known": distance is not None,
        "garmin_distance_km": distance,
        "garmin_maximum_meters": _garmin_maximum_meters(row),
        "lifetime_target_km": _garmin_lifetime_target_km(row),
        "lifetime_target_source": "garmin",
        "revision": 1,
        "updated_at": now,
        "source": "garmin-initial-sync",
    }
    db.execute(
        "INSERT OR IGNORE INTO kv(key,value,updated_at) VALUES(?,?,?)",
        (EQUIPMENT_PREFIX + item_id, json.dumps(item), now),
    )


def _refresh_garmin_distances(
    db: Any, rows: list[dict[str, Any]], by_garmin: dict[str, dict[str, Any]], now: str
) -> None:
    for row in rows:
        linked = by_garmin.get(str(row.get("gearUUID") or ""))
        if linked is None:
            continue
        changed = _update_garmin_gear(linked, row)
        if not changed:
            continue
        linked["updated_at"] = now
        db.execute(
            "UPDATE kv SET value=?, updated_at=? WHERE key=?",
            (json.dumps(linked), now, EQUIPMENT_PREFIX + str(linked["id"])),
        )


def _validate_equipment_children(
    db: Any, item_id: str, parent_id: str | None, payload: dict[str, Any]
) -> None:
    children = [
        json.loads(row["value"])
        for row in db.execute(
            "SELECT value FROM kv WHERE key LIKE 'equipment:%' AND json_extract(value, '$.parent_id')=?",
            (item_id,),
        ).fetchall()
    ]
    invalid_parent = parent_id or payload["kind"] == "component"
    mismatched_sport = any(item["sport"] != payload["sport"] for item in children)
    if children and (invalid_parent or mismatched_sport):
        raise AppError(
            409,
            "Vorhandene Komponenten ben?tigen diesen Hauptgegenstand und dessen Sportart.",
        )


def _garmin_distance_km(row: dict) -> float | None:
    stats = row.get("stats") or {}
    distance = number(stats.get("totalDistance")) if isinstance(stats, dict) else None
    return round(distance / 1000, 2) if distance is not None else None


def _garmin_maximum_meters(row: dict) -> float | None:
    value = number(row.get("maximumMeters"))
    return value if _valid_positive_number(value) else None


def _garmin_lifetime_target_km(row: dict) -> float | None:
    maximum_meters = _garmin_maximum_meters(row)
    return round(maximum_meters / 1000, 2) if maximum_meters is not None else None


def _valid_positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _lifetime_projection(usage_km: Any, target_km: Any) -> dict[str, float] | None:
    usage = number(usage_km)
    if usage is None or not _valid_positive_number(target_km):
        return None
    percent = usage / target_km * 100
    if not math.isfinite(percent):
        return None
    return {
        "usage_km": round(usage, 2),
        "target_km": round(target_km, 2),
        "percent": round(percent, 1),
        "progress_percent": round(min(100.0, percent), 1),
    }


def _garmin_sport(row: dict) -> str:
    value = _garmin_gear_text(row)
    if any(token in value for token in ("cycling", "cycle", "ride", "radfahren")):
        return "Ride"
    if _garmin_kind(row) in {"bike", "component"}:
        return "Ride"
    if _garmin_kind(row) == "shoes" or any(
        token in value for token in ("running", "laufen", "run")
    ):
        return "Run"
    if "swim" in value:
        return "Swim"
    return "Other"


def _garmin_kind(row: dict) -> str:
    value = _garmin_gear_text(row)
    if any(
        token in value for token in ("shoe", "footwear", "laufschuh", "running shoe")
    ):
        return "shoes"
    if any(
        token in value
        for token in (
            "component",
            "part",
            "kette",
            "chain",
            "cassette",
            "crank",
            "derailleur",
            "schaltwerk",
            "rotor",
            "brake",
            "bremse",
            "reifen",
            "tire",
            "tyre",
            "wheel",
            "laufrad",
            "pedal",
            "chainring",
            "kettenblatt",
            "handlebar",
            "lenker",
            "groupset",
        )
    ):
        return "component"
    if any(token in value for token in ("bike", "bicycle", "biking", "rad")):
        return "bike"
    return "other"


def _garmin_gear_text(row: dict) -> str:
    return " ".join(
        str(row.get(key) or "").lower()
        for key in ("gearTypeName", "gearName", "activityTypeName")
    )


def _garmin_status(row: dict) -> str:
    value = _garmin_raw_status(row).lower()
    return (
        "archived"
        if any(
            token in value
            for token in ("retir", "archiv", "inactive", "inaktiv", "ausgemustert")
        )
        else "active"
    )


def _garmin_raw_status(row: dict) -> str:
    return str(row.get("gearStatusName") or "").strip()[:100]


def _garmin_item(row: dict) -> dict[str, Any]:
    stats = row.get("stats") or {}
    distance = number(stats.get("totalDistance")) if isinstance(stats, dict) else None
    goal = _garmin_maximum_meters(row)
    distance_km = round(distance / 1000, 2) if distance is not None else None
    goal_km = round(goal / 1000, 2) if goal is not None else None
    lifetime = _lifetime_projection(distance_km, goal_km)
    return {
        "id": str(row.get("gearUUID") or ""),
        "name": str(row.get("gearName") or "Ausr\u00fcstung")[:200],
        "kind": str(row.get("gearTypeName") or "")[:100],
        "status": _garmin_status(row),
        "garmin_status": _garmin_raw_status(row),
        "distance_km": distance_km,
        "goal_km": goal_km,
        "usage_percent": lifetime["percent"] if lifetime else None,
        "lifetime": lifetime,
        "sessions": number(stats.get("totalActivities"))
        if isinstance(stats, dict)
        else None,
        "source": "Garmin Connect",
    }


def _equipment_identity(payload: dict, today: date) -> tuple[str, date, str]:
    name = str(payload.get("name") or "").strip()
    if (
        not name
        or len(name) > 200
        or payload.get("sport")
        not in {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining", "Other"}
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
    if not date(2010, 1, 1) <= start <= today:
        raise AppError(400, "Ausrüstungsbeginn liegt außerhalb des gültigen Zeitraums.")

    return name, start, item_id


def _equipment_amounts(payload: dict) -> dict[str, Any]:
    amounts = {}
    for field, maximum in (
        ("initial_distance_km", 1000000),
        ("initial_hours", 100000),
        ("maintenance_km", 1000000),
        ("maintenance_hours", 100000),
        ("lifetime_target_km", 1000000),
    ):
        value = payload.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= maximum
        ):
            raise AppError(400, "Ausrüstungszähler oder Wartungsintervall ungültig.")
        if field.startswith("initial") and value is None:
            raise AppError(
                400, "Anfangsstand muss ausdrücklich als Zahl angegeben werden."
            )
        if field == "lifetime_target_km" and value is not None and value <= 0:
            raise AppError(400, "Lifetime target must be positive.")
        amounts[field] = value

    return amounts


def _equipment_parent(db: Any, payload: dict, item_id: str) -> str | None:
    parent_id = payload.get("parent_id") or None
    if payload["kind"] == "component" and not parent_id:
        raise AppError(400, "Eine Komponente benötigt einen Hauptgegenstand.")
    if parent_id:
        parent = db.execute(
            SELECT_VALUE, (EQUIPMENT_PREFIX + str(parent_id),)
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

    return parent_id


def _update_usage(
    item: dict,
    rows: list[dict],
    assignments: dict,
    maintenance: list[dict],
    today: date,
    garmin_usage: dict[str, float | None],
) -> None:
    eligible = [
        row
        for row in rows
        if (assignments.get(str(row.get("id"))) or {}).get("equipment_id")
        == (item.get("parent_id") or item["id"])
        and item["start_date"]
        <= str(row.get("start_date_local") or "")[:10]
        <= today.isoformat()
    ]
    events = sorted(
        [row for row in maintenance if row["equipment_id"] == item["id"]],
        key=lambda row: (row["date"], row["observed_at"]),
    )
    distance = sum(number(row.get("distance")) or 0 for row in eligible) / 1000
    garmin_distance = item.get("garmin_distance_km")
    if garmin_distance is None:
        garmin_distance = garmin_usage.get(str(item.get("garmin_uuid")))
    hours = sum(number(row.get("moving_time")) or 0 for row in eligible) / 3600
    if item.get("garmin_uuid") and garmin_distance is None:
        distance_km = None
    else:
        total_distance = (
            garmin_distance
            if garmin_distance is not None
            else item["initial_distance_km"] + distance
        )
        distance_km = round(total_distance, 2)
    item["usage"] = {
        "distance_km": distance_km,
        "hours": round(item["initial_hours"] + hours, 2),
        "assigned_sessions": len(eligible),
        "distance_known_sessions": sum(
            number(row.get("distance")) is not None for row in eligible
        ),
        "time_known_sessions": sum(
            number(row.get("moving_time")) is not None for row in eligible
        ),
        **_maintenance_usage(item, eligible, events, garmin_distance),
    }
    target_km = item.get("lifetime_target_km")
    if target_km is None and _valid_positive_number(item.get("garmin_maximum_meters")):
        target_km = item["garmin_maximum_meters"] / 1000
    item["lifetime"] = _lifetime_projection(distance_km, target_km)
    item["maintenance"] = events


def _maintenance_usage(
    item: dict,
    eligible: list[dict],
    events: list[dict],
    garmin_distance: float | None = None,
) -> dict[str, Any]:
    latest = events[-1] if events else None
    ambiguous, since = _maintenance_sessions(eligible, latest)
    distance = _maintenance_distance(item, since, latest, garmin_distance)
    hours = _maintenance_hours(item, since, latest)
    reached = _maintenance_reached(item, distance, hours)
    uncertain = _maintenance_uncertain(item, since, ambiguous) or (
        bool(item.get("maintenance_km")) and distance is None
    )
    if reached:
        due = True
    elif uncertain:
        due = None
    else:
        due = False
    return {
        "maintenance_distance_km": round(distance, 2) if distance is not None else None,
        "maintenance_hours": round(hours, 2),
        "maintenance_due": due,
        "maintenance_same_day_sessions": len(ambiguous),
        "maintenance_coverage": "partial" if uncertain else "known_assignments",
    }


def _maintenance_sessions(
    eligible: list[dict], latest: dict | None
) -> tuple[list[dict], list[dict]]:
    ambiguous = [
        row
        for row in eligible
        if latest and str(row.get("start_date_local") or "").startswith(latest["date"])
    ]
    since = [
        row
        for row in eligible
        if not latest or str(row.get("start_date_local") or "")[:10] > latest["date"]
    ]
    return ambiguous, since


def _maintenance_distance(
    item: dict, since: list[dict], latest: dict | None, garmin_distance: float | None
) -> float | None:
    if item.get("garmin_uuid"):
        if garmin_distance is None:
            return None
        if latest and latest.get("distance_km") is None:
            return None
        baseline = number(latest.get("distance_km")) if latest else 0
        return max(0, garmin_distance - (baseline or 0))
    local_distance = sum(number(row.get("distance")) or 0 for row in since) / 1000
    return local_distance + (item["initial_distance_km"] if not latest else 0)


def _maintenance_hours(item: dict, since: list[dict], latest: dict | None) -> float:
    hours = sum(number(row.get("moving_time")) or 0 for row in since) / 3600
    return hours + (item["initial_hours"] if not latest else 0)


def _maintenance_reached(item: dict, distance: float | None, hours: float) -> bool:
    distance_due = bool(
        item.get("maintenance_km")
        and distance is not None
        and distance >= item["maintenance_km"]
    )
    hours_due = bool(
        item.get("maintenance_hours") and hours >= item["maintenance_hours"]
    )
    return distance_due or hours_due


def _maintenance_uncertain(
    item: dict, since: list[dict], ambiguous: list[dict]
) -> bool:
    return bool(ambiguous) or any(
        item.get(interval) and any(number(row.get(measure)) is None for row in since)
        for interval, measure in (
            ("maintenance_km", "distance"),
            ("maintenance_hours", "moving_time"),
        )
    )


def _preserve_equipment_metadata(
    saved: dict[str, Any], previous: dict[str, Any] | None, payload: dict[str, Any]
):
    if previous and "lifetime_target_km" not in payload:
        saved["lifetime_target_km"] = previous.get("lifetime_target_km")
        if previous.get("lifetime_target_source"):
            saved["lifetime_target_source"] = previous["lifetime_target_source"]
    elif "lifetime_target_km" in payload:
        saved["lifetime_target_source"] = "local"
    if previous and previous.get("garmin_uuid"):
        saved["garmin_uuid"] = previous["garmin_uuid"]
        if previous.get("garmin_distance_km") is not None:
            saved["garmin_distance_km"] = previous["garmin_distance_km"]
        for field in ("garmin_maximum_meters", "garmin_status"):
            if previous.get(field) is not None:
                saved[field] = previous[field]


def _update_garmin_gear(linked: dict[str, Any], row: dict[str, Any]) -> bool:
    changed = False
    distance = _garmin_distance_km(row)
    if distance is not None and linked.get("garmin_distance_km") != distance:
        linked["garmin_distance_km"] = distance
        changed = True
    raw_status = _garmin_raw_status(row)
    if linked.get("garmin_status") != raw_status:
        linked["garmin_status"] = raw_status
        changed = True
    maximum_meters = _garmin_maximum_meters(row)
    if maximum_meters is not None:
        if linked.get("garmin_maximum_meters") != maximum_meters:
            linked["garmin_maximum_meters"] = maximum_meters
            changed = True
        if linked.get(
            "lifetime_target_source"
        ) == "garmin" or not _valid_positive_number(linked.get("lifetime_target_km")):
            linked["lifetime_target_km"] = round(maximum_meters / 1000, 2)
            linked["lifetime_target_source"] = "garmin"
            changed = True
    return changed
