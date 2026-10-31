"""Explicit gear assignments and athlete-defined maintenance usage counters."""

import json
import math
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Protocol

from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.domain_records import GearActivityLink, GearItem
from backend.canonical.stored_sports import (
    StoredSport,
    activity_type_environment,
    resolve_equipment_sport,
)
from backend.canonical.vocabulary import ProviderId, Sport
from backend.db import canonical_store, garmin_store
from backend.errors import AppError

EQUIPMENT_PREFIX = "equipment:"
SELECT_VALUE = "SELECT value FROM kv WHERE key=?"
GARMIN_GEAR_SOURCE = "garmin_gear"
# The read lists at most this many assignments, whole activities only; usage
# counts all of them.
ASSIGNMENT_LIST_LIMIT = 2000
GARMIN_INITIAL_SOURCE = "garmin-initial-sync"
SPORT_DERIVATION_SHARE = 0.75
SPORT_DERIVATION_MIN_ROWS = 3


class GearReader(Protocol):
    """Reads the canonical gear and gear-to-activity links."""

    def gear_items(self, db: Any) -> tuple[GearItem, ...]: ...

    def gear_activity_links(self, db: Any) -> tuple[GearActivityLink, ...]: ...


# Garmin gear id -> the provider activity ids it lists; only known lists appear.
GearActivities = dict[str, list[str]]


def canonical_garmin_gear(
    reader: GearReader | None, db: Any
) -> tuple[list[GearItem], GearActivities]:
    """Return the canonical Garmin gear and the activity list of each listed item.

    An item without a known activity list (``activity_list_partial`` None) is left
    out of the lists, so its activities are unknown, not empty. Without a reader
    there is no gear.
    """
    if reader is None:
        return [], {}
    items = [
        item
        for item in reader.gear_items(db)
        if item.provenance.provider is ProviderId.GARMIN
    ]
    activity_ids: GearActivities = {}
    for link in reader.gear_activity_links(db):
        if link.provenance.provider is ProviderId.GARMIN:
            activity_ids.setdefault(link.gear_id, []).append(link.provider_activity_id)
    listed = {
        item.gear_id: activity_ids.get(item.gear_id, [])
        for item in items
        if item.activity_list_partial is not None
    }
    return items, listed


class EquipmentService:
    def __init__(
        self,
        manager: Any,
        read_activity_rows: Callable[[], Sequence[dict[str, Any]]],
        today: Callable[[], date],
        utc_now: Callable[[], str],
        deduplicate: Callable[[Sequence[Any]], tuple[list[dict[str, Any]], int]],
        resolve_activity: Callable[[Any], Any] | None = None,
        gear_reader: GearReader | None = None,
    ):
        self._manager, self._read_activity_rows, self._today, self._utc_now = (
            manager,
            read_activity_rows,
            today,
            utc_now,
        )
        self._deduplicate = deduplicate
        self._gear_reader = gear_reader
        self._resolve_activity = (
            (lambda reference: reference)
            if resolve_activity is None
            else resolve_activity
        )

    def _records(self, db: Any, prefix: str, limit: int | None) -> list[dict[str, Any]]:
        """Return the newest records of a kind; a limit of None reads them all."""
        return [
            json.loads(row["value"])
            for row in db.execute(
                "SELECT value FROM kv WHERE key LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (prefix + ":%", -1 if limit is None else limit),
            ).fetchall()
        ]

    def read(
        self, item_id: str | None = None, *, activity_id: str | None = None
    ) -> dict[str, Any]:
        """Read items with usage; ``activity_id`` lists only its full assignments."""
        rows, duplicates = self._deduplicate(self._read_activity_rows())
        with self._manager.unit_of_work() as db:
            # The Garmin state carries only sync status: source, time and freshness.
            status = garmin_store.read_state(db)
            gear, listed = canonical_garmin_gear(self._gear_reader, db)
            if status.get("source") == "fixture":
                gear, listed = [], {}
            gear_initialized = (
                db.execute(SELECT_VALUE, ("garmin_equipment_initialized",)).fetchone()
                is not None
            )
            garmin_usage = {item.gear_id: _garmin_distance_km(item) for item in gear}
            items = self._records(db, "equipment", 100)
            links = _garmin_links(items, listed, rows, _gear_sessions(db, listed, rows))
            partial = _partial_garmin_history(items, gear)
            # Every explicit assignment, including an unassignment, overrides the link.
            explicit = {
                row["activity_id"]: row
                for row in self._records(db, "equipment_assignment", None)
            }
            links = {key: value for key, value in links.items() if key not in explicit}
            if item_id:
                selected = db.execute(
                    SELECT_VALUE, (EQUIPMENT_PREFIX + item_id,)
                ).fetchone()
                if not selected:
                    raise AppError(404, "Ausrüstung nicht gefunden.")
                items = [json.loads(selected["value"])]
            assignments = _effective_assignments(rows, explicit, links)
            maintenance = self._records(db, "equipment_maintenance", 1000)
        for item in items:
            _update_usage(
                item,
                rows,
                assignments,
                maintenance,
                self._today(),
                garmin_usage,
                (item.get("parent_id") or item["id"]) in partial,
            )
        return {
            "items": items,
            "garmin_items": []
            if gear_initialized
            else [
                item
                for item in (_garmin_item(item) for item in gear)
                if item["id"] not in {str(local.get("garmin_uuid")) for local in items}
            ],
            "garmin_synced_at": status.get("synced_at"),
            "garmin_freshness": (status.get("source_freshness") or {})
            .get("gear", {})
            .get("freshness"),
            "assignments": list(assignments.get(activity_id, ()))
            if activity_id
            else _assignment_list(assignments),
            "excluded_duplicates": duplicates,
            "scope": "Known canonical activities with explicit assignments, or that Garmin lists for the gear of a Garmin-linked main item (an explicit assignment, including unassigned, always wins; an activity Garmin lists for several main items links to each of them, like Garmin's own totals; an item without a Garmin activity list links nothing), plus confirmed initial usage. Missing provider history or measurements makes counters incomplete; no inferred favorite gear. A truncated or outdated Garmin activity list makes the maintenance of intervals counted from sessions partial. Maintenance includes only later calendar days, same-day order is unknown. Limits: 100 items, 1000 maintenance events; usage counts every assignment, but the list shows only the first 2000 without splitting an activity's gear, explicit ones newest first, then Garmin links; an activity's own read lists all of its assignments.",
        }

    def sync_garmin_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Import Garmin gear once, then refresh only Garmin-owned mileage.

        ``snapshot`` gives only the gear's sync freshness. The gear is the canonical
        Garmin gear the sync stored before calling this.
        """
        if not _current_garmin_gear(snapshot):
            return
        with self._manager.reader() as db:
            gear, listed = canonical_garmin_gear(self._gear_reader, db)
        # A current but empty or malformed inventory is not proof that the
        # initial import succeeded. Leave initialization open for recovery.
        if not gear:
            return
        # Garmin lists no gear activities: skip reading every activity row.
        activity_rows = (
            self._deduplicate(self._read_activity_rows())[0] if listed else []
        )
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
                for item in gear:
                    if item.gear_id not in by_garmin:
                        _insert_initial_garmin_item(db, item, self._today(), now)
            # An explicit assignment, including an unassignment, overrides the link.
            explicit = {
                row["activity_id"]
                for row in self._records(db, "equipment_assignment", None)
            }
            links = _garmin_links(
                local_rows,
                listed,
                activity_rows,
                _gear_sessions(db, listed, activity_rows),
            )
            derived = _derived_sports(
                local_rows,
                activity_rows,
                {key: value for key, value in links.items() if key not in explicit},
            )
            _refresh_garmin_distances(db, gear, by_garmin, now, derived)
            if not initialized:
                db.execute(
                    "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                    ("garmin_equipment_initialized", "1", now),
                )

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "id",
            "expected_revision",
            "name",
            "sport",
            "environment",
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
            sport = _payload_sport(payload)
            saved = {
                "id": item_id,
                "name": name,
                **_equipment_sport_fields(sport),
                "kind": payload["kind"],
                "status": payload.get("status", "active"),
                "parent_id": parent_id,
                "start_date": start.isoformat(),
                **amounts,
                "revision": previous["revision"] + 1 if previous else 1,
                "updated_at": self._utc_now(),
                "source": "athlete-entered equipment",
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
        activity_id = str(self._resolve_activity(payload["activity_id"]))
        rows, _ = self._deduplicate(self._read_activity_rows())
        row = next(
            (row for row in rows if str(row.get("id")) == activity_id),
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
                or _item_pair(equipment)
                != _stored_pair(resolve_equipment_sport(row.get("type")))
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


def _payload_sport(payload: dict[str, Any]) -> StoredSport | None:
    """Return the canonical sport of submitted equipment (canonical value or legacy token)."""
    return resolve_equipment_sport(payload.get("sport"), payload.get("environment"))


def _stored_pair(stored: StoredSport | None) -> tuple[str, str] | None:
    """Return the comparable sport pair; activity types blur indoor and outdoor."""
    if stored is None:
        return None
    return (stored.sport.value, activity_type_environment(stored.environment).value)


def _item_pair(item: dict[str, Any]) -> tuple[str, str] | None:
    """Return the canonical sport pair of a stored equipment item."""
    return _stored_pair(
        resolve_equipment_sport(item.get("sport"), item.get("environment"))
    )


def _equipment_sport_fields(stored: StoredSport | None) -> dict[str, Any]:
    if stored is None:
        raise AppError(400, "Name, Sport, Art oder Status der Ausrüstung ungültig.")
    return {
        "sport": stored.sport.value,
        "environment": stored.environment.value,
        "sport_pending": stored.sport is Sport.OTHER,
    }


def _current_garmin_gear(snapshot: Any) -> bool:
    return bool(
        isinstance(snapshot, dict)
        and (snapshot.get("source_freshness") or {}).get("gear", {}).get("freshness")
        == "current"
    )


def _insert_initial_garmin_item(db: Any, gear: GearItem, today: date, now: str) -> None:
    distance = _garmin_distance_km(gear)
    kind = _garmin_kind(gear)
    sport = _garmin_sport(gear)
    gear_id = gear.gear_id
    item_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "garmin:" + gear_id))
    item = {
        "id": item_id,
        "name": (gear.name or "Ausr\u00fcstung")[:200],
        **_equipment_sport_fields(resolve_equipment_sport(sport)),
        "kind": kind,
        "parent_pending": kind == "component",
        "status": _garmin_status(gear),
        "garmin_status": _garmin_raw_status(gear),
        "parent_id": None,
        "start_date": today.isoformat(),
        "initial_distance_km": distance or 0,
        "initial_hours": 0,
        "maintenance_km": None,
        "maintenance_hours": None,
        "garmin_uuid": gear_id,
        "initial_distance_known": distance is not None,
        "garmin_distance_km": distance,
        "garmin_maximum_meters": _garmin_maximum_meters(gear),
        "lifetime_target_km": _garmin_lifetime_target_km(gear),
        "lifetime_target_source": ProviderId.GARMIN.value,
        "revision": 1,
        "updated_at": now,
        "source": GARMIN_INITIAL_SOURCE,
    }
    db.execute(
        "INSERT OR IGNORE INTO kv(key,value,updated_at) VALUES(?,?,?)",
        (EQUIPMENT_PREFIX + item_id, json.dumps(item), now),
    )


def _refresh_garmin_distances(
    db: Any,
    gear: list[GearItem],
    by_garmin: dict[str, dict[str, Any]],
    now: str,
    derived_sports: dict[str, StoredSport],
) -> None:
    for item in gear:
        linked = by_garmin.get(item.gear_id)
        if linked is None:
            continue
        changed = _update_garmin_gear(linked, item)
        stored = derived_sports.get(str(linked["id"]))
        if stored is not None and linked.get("sport_pending"):
            linked.update(_equipment_sport_fields(stored))
            changed = True
        if not changed:
            continue
        linked["updated_at"] = now
        db.execute(
            "UPDATE kv SET value=?, updated_at=? WHERE key=?",
            (json.dumps(linked), now, EQUIPMENT_PREFIX + str(linked["id"])),
        )


def _equipment_children(db: Any, item_id: str) -> list[dict[str, Any]]:
    return [
        json.loads(row["value"])
        for row in db.execute(
            "SELECT value FROM kv WHERE key LIKE 'equipment:%' AND json_extract(value, '$.parent_id')=?",
            (item_id,),
        ).fetchall()
    ]


def _validate_equipment_children(
    db: Any, item_id: str, parent_id: str | None, payload: dict[str, Any]
) -> None:
    children = _equipment_children(db, item_id)
    invalid_parent = parent_id or payload["kind"] == "component"
    mismatched_sport = any(
        _item_pair(item) != _stored_pair(_payload_sport(payload)) for item in children
    )
    if children and (invalid_parent or mismatched_sport):
        raise AppError(
            409,
            "Vorhandene Komponenten benötigen diesen Hauptgegenstand und dessen Sportart.",
        )


def _garmin_distance_km(gear: GearItem) -> float | None:
    distance = number(gear.total_distance_m)
    return round(distance / 1000, 2) if distance is not None else None


def _garmin_maximum_meters(gear: GearItem) -> float | None:
    value = number(gear.maximum_distance_m)
    return value if _valid_positive_number(value) else None


def _garmin_lifetime_target_km(gear: GearItem) -> float | None:
    maximum_meters = _garmin_maximum_meters(gear)
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


def _garmin_sport(gear: GearItem) -> str:
    value = _garmin_gear_text(gear)
    if any(token in value for token in ("cycling", "cycle", "ride", "radfahren")):
        return "Ride"
    if _garmin_kind(gear) in {"bike", "component"}:
        return "Ride"
    if _garmin_kind(gear) == "shoes" or any(
        token in value for token in ("running", "laufen", "run")
    ):
        return "Run"
    if "swim" in value:
        return "Swim"
    return "Other"


def _garmin_kind(gear: GearItem) -> str:
    value = _garmin_gear_text(gear)
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


def _garmin_gear_text(gear: GearItem) -> str:
    return " ".join(
        (text or "").lower()
        for text in (gear.type_label, gear.name, gear.activity_type_label)
    )


def _garmin_status(gear: GearItem) -> str:
    value = _garmin_raw_status(gear).lower()
    return (
        "archived"
        if any(
            token in value
            for token in ("retir", "archiv", "inactive", "inaktiv", "ausgemustert")
        )
        else "active"
    )


def _garmin_raw_status(gear: GearItem) -> str:
    return (gear.status_label or "").strip()[:100]


def _garmin_item(gear: GearItem) -> dict[str, Any]:
    distance_km = _garmin_distance_km(gear)
    goal = _garmin_maximum_meters(gear)
    goal_km = round(goal / 1000, 2) if goal is not None else None
    lifetime = _lifetime_projection(distance_km, goal_km)
    return {
        "id": gear.gear_id,
        "name": (gear.name or "Ausr\u00fcstung")[:200],
        "kind": (gear.type_label or "")[:100],
        "status": _garmin_status(gear),
        "garmin_status": _garmin_raw_status(gear),
        "distance_km": distance_km,
        "goal_km": goal_km,
        "usage_percent": lifetime["percent"] if lifetime else None,
        "lifetime": lifetime,
        "sessions": number(gear.total_activities),
        "source": "Garmin Connect",
    }


def _equipment_identity(payload: dict, today: date) -> tuple[str, date, str]:
    name = str(payload.get("name") or "").strip()
    if (
        not name
        or len(name) > 200
        or _payload_sport(payload) is None
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
            or _item_pair(json.loads(parent["value"]))
            != _stored_pair(_payload_sport(payload))
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
    partial_history: bool = False,
) -> None:
    eligible = [row for row in rows if _counts_for(item, row, assignments, today)]
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
        **_maintenance_usage(item, eligible, events, garmin_distance, partial_history),
    }
    target_km = item.get("lifetime_target_km")
    if target_km is None and _valid_positive_number(item.get("garmin_maximum_meters")):
        target_km = item["garmin_maximum_meters"] / 1000
    item["lifetime"] = _lifetime_projection(distance_km, target_km)
    item["maintenance"] = events


def _counts_for(item: dict, row: dict, assignments: dict, today: date) -> bool:
    """Return whether the row's effective assignment counts toward the item today.

    An item counts rows from its start date on. Garmin lists a gear item's whole
    history, so rows it links are not cut off at the date the main item was
    imported. A component still counts only from its own start date.
    """
    owner = item.get("parent_id") or item["id"]
    assignment = next(
        (
            assignment
            for assignment in assignments.get(str(row.get("id")), ())
            if assignment.get("equipment_id") == owner
        ),
        None,
    )
    day = iso_date_prefix(str(row.get("start_date_local") or ""))
    if assignment is None or not day:
        return False
    garmin_history = assignment.get("source") == GARMIN_GEAR_SOURCE and not item.get(
        "parent_id"
    )
    started = garmin_history or item["start_date"] <= day
    return started and day <= today.isoformat()


def _maintenance_usage(
    item: dict,
    eligible: list[dict],
    events: list[dict],
    garmin_distance: float | None = None,
    partial_history: bool = False,
) -> dict[str, Any]:
    latest = events[-1] if events else None
    ambiguous, since = _maintenance_sessions(eligible, latest)
    distance = _maintenance_distance(item, since, latest, garmin_distance)
    hours = _maintenance_hours(item, since, latest)
    reached = _maintenance_reached(item, distance, hours)
    uncertain = (
        _maintenance_uncertain(item, since, ambiguous)
        or (bool(item.get("maintenance_km")) and distance is None)
        or (partial_history and _session_counted_interval(item))
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
        if not latest
        or iso_date_prefix(str(row.get("start_date_local") or "")) > latest["date"]
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


def _session_counted_interval(item: dict) -> bool:
    """Return whether a maintenance interval depends on the linked sessions.

    Hours always come from sessions. A Garmin item's distance is Garmin's own total.
    """
    return bool(
        item.get("maintenance_hours")
        or (item.get("maintenance_km") and not item.get("garmin_uuid"))
    )


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


def _partial_garmin_history(
    items: list[dict[str, Any]], gear: list[GearItem]
) -> set[str]:
    """Return main item ids whose Garmin activity list is truncated or outdated."""
    partial = {entry.gear_id for entry in gear if entry.activity_list_partial}
    return {
        item["id"]
        for item in items
        if item.get("garmin_uuid") and str(item["garmin_uuid"]) in partial
    }


def _gear_sessions(
    db: Any, listed: GearActivities, rows: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the canonical sessions of the listed Garmin activities and the rows."""
    garmin_ids = [
        str(activity_id)
        for activity_ids in listed.values()
        for activity_id in activity_ids
    ]
    if not garmin_ids:
        return {}, {}
    return (
        canonical_store.provider_activity_sessions(
            db, ProviderId.GARMIN.value, garmin_ids
        ),
        canonical_store.provider_activity_sessions(
            db, ProviderId.INTERVALS.value, [str(row.get("id")) for row in rows]
        ),
    )


def _garmin_links(
    items: list[dict[str, Any]],
    activity_ids: GearActivities,
    rows: list[dict[str, Any]],
    sessions: tuple[dict[str, str], dict[str, str]] = ({}, {}),
) -> dict[str, list[str]]:
    """Map activity ids to every main item whose Garmin gear lists the activity.

    Garmin's own gear-to-activity list is the link. Garmin activity ids reach the
    stored Intervals.icu rows through their canonical session (``sessions`` holds
    the effective session of each Garmin activity and of each row) and through an
    ``external_id`` equal to the Garmin id. Only the given (deduplicated) rows
    can link, so a duplicate recording counts once. Components and items without
    a Garmin gear item that lists activities never link; a gear item without a
    known activity list is unknown, not empty. Garmin records several gear items
    per activity and counts the activity in each item's totals, so an activity
    listed for several main items links to each of them.
    """
    if not activity_ids:
        return {}
    by_garmin = _rows_by_garmin_id(rows, sessions)
    owners: dict[str, set[str]] = {}
    for item in items:
        if item.get("parent_id") or item.get("kind") == "component":
            continue
        for activity_id in _listed_row_ids(
            activity_ids.get(str(item.get("garmin_uuid")), []), by_garmin
        ):
            owners.setdefault(activity_id, set()).add(item["id"])
    return {
        activity_id: sorted(equipment_ids)
        for activity_id, equipment_ids in owners.items()
    }


def _listed_row_ids(garmin_ids: list[Any], by_garmin: dict[str, set[str]]) -> set[str]:
    return {
        activity_id
        for garmin_id in garmin_ids
        for activity_id in by_garmin.get(str(garmin_id), ())
    }


def _rows_by_garmin_id(
    rows: list[dict[str, Any]],
    sessions: tuple[dict[str, str], dict[str, str]] = ({}, {}),
) -> dict[str, set[str]]:
    row_ids = {str(row.get("id")) for row in rows}
    by_garmin = _rows_by_garmin_session(row_ids, *sessions)
    for row in rows:
        if row.get("external_id") not in (None, ""):
            by_garmin.setdefault(str(row["external_id"]), set()).add(str(row.get("id")))
    return by_garmin


def _rows_by_garmin_session(
    row_ids: set[str], garmin_sessions: dict[str, str], row_sessions: dict[str, str]
) -> dict[str, set[str]]:
    """Map each Garmin activity to the rows bundled into its canonical session."""
    rows_by_session: dict[str, set[str]] = {}
    for row_id in row_ids:
        if (session := row_sessions.get(row_id)) is not None:
            rows_by_session.setdefault(session, set()).add(row_id)
    by_garmin: dict[str, set[str]] = {}
    for garmin_id, session in garmin_sessions.items():
        for row_id in rows_by_session.get(session, ()):
            by_garmin.setdefault(garmin_id, set()).add(row_id)
    return by_garmin


def _effective_assignments(
    rows: list[dict[str, Any]],
    explicit: dict[str, dict[str, Any]],
    links: dict[str, list[str]],
) -> dict[str, list[dict[str, Any]]]:
    """Return each activity's explicit assignment or its Garmin gear links.

    An explicit record, including one that unassigns, replaces every Garmin link
    of its activity. Garmin links carry no sport check: shoes used for walks and
    runs count both.
    """
    effective = {activity_id: [row] for activity_id, row in explicit.items()}
    for row in rows:
        activity_id = str(row.get("id"))
        if activity_id not in effective and activity_id in links:
            effective[activity_id] = [
                {
                    "activity_id": activity_id,
                    "equipment_id": equipment_id,
                    "source": GARMIN_GEAR_SOURCE,
                }
                for equipment_id in links[activity_id]
            ]
    return effective


def _assignment_list(
    assignments: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten the assignments up to the list limit, keeping each activity whole."""
    listed: list[dict[str, Any]] = []
    for activity_assignments in assignments.values():
        if len(listed) + len(activity_assignments) > ASSIGNMENT_LIST_LIMIT:
            break
        listed.extend(activity_assignments)
    return listed


def _derived_sports(
    items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    links: dict[str, list[str]],
) -> dict[str, StoredSport]:
    """Return the sport an open item's linked activities agree on.

    Only items still as imported from Garmin, with an open sport, no components
    and no children derive one; an athlete-saved item keeps its sport. A
    single sport pair must cover at least three quarters of all linked activities,
    unknown and other types included, and at least three of them.
    """
    open_ids = _sport_derivable_ids(items)
    counts: dict[str, Counter[tuple[str, str] | None]] = {}
    stored: dict[tuple[str, str], StoredSport] = {}
    for row in rows:
        equipment_ids = [
            equipment_id
            for equipment_id in links.get(str(row.get("id")), ())
            if equipment_id in open_ids
        ]
        if not equipment_ids:
            continue
        sport = resolve_equipment_sport(row.get("type"))
        pair = _stored_pair(sport) if sport and sport.sport is not Sport.OTHER else None
        for equipment_id in equipment_ids:
            counts.setdefault(equipment_id, Counter())[pair] += 1
        if sport and pair:
            stored.setdefault(pair, sport)
    derived = {}
    for equipment_id, counter in counts.items():
        top = _dominant_pair(counter)
        if top is not None:
            derived[equipment_id] = stored[top]
    return derived


def _sport_derivable_ids(items: list[dict[str, Any]]) -> set[str]:
    """Return main items still as imported from Garmin with an open sport."""
    parents = {item.get("parent_id") for item in items}
    return {
        str(item["id"])
        for item in items
        if item.get("sport_pending")
        and item.get("source") == GARMIN_INITIAL_SOURCE
        and not item.get("parent_id")
        and item.get("kind") != "component"
        and item["id"] not in parents
    }


def _dominant_pair(counter: Counter[tuple[str, str] | None]) -> tuple[str, str] | None:
    """Return the sport pair that meets the derivation count and share."""
    top = max(
        (pair for pair in counter if pair is not None),
        key=counter.__getitem__,
        default=None,
    )
    if top is None or counter[top] < SPORT_DERIVATION_MIN_ROWS:
        return None
    return top if counter[top] / counter.total() >= SPORT_DERIVATION_SHARE else None


def _update_garmin_gear(linked: dict[str, Any], gear: GearItem) -> bool:
    changed = False
    distance = _garmin_distance_km(gear)
    if distance is not None and linked.get("garmin_distance_km") != distance:
        linked["garmin_distance_km"] = distance
        changed = True
    raw_status = _garmin_raw_status(gear)
    if linked.get("garmin_status") != raw_status:
        linked["garmin_status"] = raw_status
        changed = True
    maximum_meters = _garmin_maximum_meters(gear)
    if maximum_meters is not None:
        if linked.get("garmin_maximum_meters") != maximum_meters:
            linked["garmin_maximum_meters"] = maximum_meters
            changed = True
        if linked.get(
            "lifetime_target_source"
        ) == ProviderId.GARMIN or not _valid_positive_number(
            linked.get("lifetime_target_km")
        ):
            linked["lifetime_target_km"] = round(maximum_meters / 1000, 2)
            linked["lifetime_target_source"] = ProviderId.GARMIN.value
            changed = True
    return changed
