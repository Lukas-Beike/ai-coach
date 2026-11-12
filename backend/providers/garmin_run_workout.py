"""Garmin running workout JSON for one local library workout.

Provider-owned and pure: maps the step blocks of a local workout (header,
repeat count and step dictionaries, parsed by the caller) onto the Garmin
workout-service document, as plain JSON in the shape of
``garminconnect.workout`` (see ``garmin_strength_workout``). Garmin has no
percent targets, so the app resolves percent and zone targets against the
athlete's references into absolute watts, bpm or m/s ranges.

Nothing is dropped or guessed silently. A step the document cannot express
(ramps, other pace units, a missing reference, an open top zone without a
bound) raises ``GarminRunMappingError`` naming the step.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.errors import AppError

# Bump when the document changes for the same unit, so it shows as changed.
PAYLOAD_VERSION: Final = 1
UNSUPPORTED_RUN_REASON: Final = "garmin_run_unsupported"
_NAME_LIMIT: Final = 80
_DESCRIPTION_LIMIT: Final = 1000
_METERS_PER_MILE: Final = 1609.344
# Percent of the basis where zone 1 starts; zone 1 has no lower limit of its own.
ZONE_FLOOR_PERCENT: Final = 50.0
_RUNNING: Final = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
_STEP_TYPES: Final = {"warmup": 1, "cooldown": 2, "interval": 3, "repeat": 6}
# Header words, folded; cooldown first because "abwarmen" contains "warm".
_COOLDOWN_WORDS: Final = ("cool", "auslauf", "abwarm", "ausroll")
_WARMUP_WORDS: Final = ("warm", "einlauf", "aufwarm")
_PACE_TARGET: Final = "pace.zone"
# Step kind -> (Garmin target type key, id).
_TARGETS: Final = {
    "power": ("power.zone", 2),
    "hr": ("heart.rate.zone", 4),
    "pace": (_PACE_TARGET, 6),
}
_ABSOLUTE_UNITS: Final = {"power": "W", "hr": "BPM"}
_ABSOLUTE = re.compile(r"(?P<low>\d+)(?:-(?P<high>\d+))?(?P<unit>W|BPM)")
_ZONE = re.compile(r"Z(?P<low>\d+)(?:-Z(?P<high>\d+))?(?:\s+(?:HR|PACE))?")
_PERCENT = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)%?(?:-(?P<high>\d+(?:\.\d+)?)%)?"
    r"(?:\s+(?P<basis>HR|LTHR|PACE|FTP))?"
)
_PACE = re.compile(
    r"(?P<low>\d+:[0-5]\d)(?:/(?P<low_unit>[A-Z0-9]+))?"
    r"(?:-(?P<high>\d+:[0-5]\d)(?:/(?P<high_unit>[A-Z0-9]+))?)?\s+PACE"
)
# (step kind, text basis) -> (GarminRunTargets field, name of the missing value)
_PERCENT_BASES: Final = {
    ("power", None): ("ftp", "Schwellenleistung (FTP)"),
    ("power", "FTP"): ("ftp", "Schwellenleistung (FTP)"),
    ("hr", "LTHR"): ("threshold_hr", "Schwellenpuls"),
    ("hr", "HR"): ("max_hr", "maximale Herzfrequenz"),
    ("pace", "PACE"): ("threshold_speed", "Schwellentempo"),
}
# The text basis a zone of each kind is percent of (heart rate: threshold pulse).
_ZONE_BASES: Final = {"power": None, "hr": "LTHR", "pace": "PACE"}


class GarminRunMappingError(AppError):
    """A local run workout the Garmin workout document cannot represent."""

    def __init__(self, message: str) -> None:
        super().__init__(422, message, reason=UNSUPPORTED_RUN_REASON)


@dataclass(frozen=True, slots=True)
class GarminRunTargets:
    """Athlete references that resolve percent and zone targets; all optional.

    The limit tuples are upper zone limits in percent of the threshold with the
    open top zone left out, as in ``ZoneSettings``. ``hr_zone_basis`` is the bpm
    the heart-rate limits are percent of (the threshold heart rate when unset).
    """

    ftp: float | None = None
    threshold_hr: float | None = None
    max_hr: float | None = None
    threshold_speed: float | None = None
    hr_zone_basis: float | None = None
    power_limits: tuple[float, ...] = ()
    hr_limits: tuple[float, ...] = ()
    pace_limits: tuple[float, ...] = ()


def run_workout(
    *,
    name: str,
    description: str,
    blocks: Sequence[Mapping[str, Any]],
    targets: GarminRunTargets | None = None,
) -> dict[str, Any]:
    """Return the Garmin running workout for the step blocks or raise a mapping error."""
    resolved = targets or GarminRunTargets()
    steps: list[dict[str, Any]] = []
    order = number = 0
    seconds = 0.0
    for block in blocks:
        repeat = int(block.get("repeat") or 1)
        step_type = _step_type(str(block.get("header") or ""))
        group_order = 0
        if repeat > 1:
            order += 1
            group_order = order
        built = []
        for step in block["steps"]:
            number += 1
            order += 1
            built.append(_executable(order, number, step, step_type, resolved))
            seconds += float(step.get("duration", 0)) * repeat
        steps.extend(built if repeat == 1 else [_group(group_order, repeat, built)])
    if not steps:
        raise GarminRunMappingError(
            "Die Einheit hat keine strukturierten Trainingsschritte für Garmin."
        )
    return {
        "workoutName": (str(name).strip() or "Lauf")[:_NAME_LIMIT],
        "description": str(description or "")[:_DESCRIPTION_LIMIT],
        "sportType": dict(_RUNNING),
        "estimatedDurationInSecs": round(seconds),
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": dict(_RUNNING), "workoutSteps": steps}
        ],
    }


def comparable_steps(workout: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    """Return what Garmin acts on in ``workout``, flattened in order.

    Ids, display orders, descriptions, nulls and int-versus-float spelling do
    not count, so the document sent equals the same workout read back. A repeat
    group is a ``("repeat", iterations, child count)`` marker before its children.
    """
    flat: list[tuple[Any, ...]] = []
    for segment in workout.get("workoutSegments") or []:
        if isinstance(segment, Mapping):
            _flatten(segment.get("workoutSteps"), flat)
    return flat


def _flatten(steps: Any, flat: list[tuple[Any, ...]]) -> None:
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, Mapping):
            continue
        if step.get("type") == "RepeatGroupDTO":
            children = step.get("workoutSteps") or []
            flat.append(
                ("repeat", int(step.get("numberOfIterations") or 0), len(children))
            )
            _flatten(children, flat)
            continue
        target = _key(step.get("targetType"), "workoutTargetTypeKey")
        flat.append(
            (
                _key(step.get("stepType"), "stepTypeKey"),
                _key(step.get("endCondition"), "conditionTypeKey"),
                _rounded(step.get("endConditionValue"), 1),
                target,
                *(
                    _rounded(step.get(field), 3 if target == _PACE_TARGET else 0)
                    for field in ("targetValueOne", "targetValueTwo")
                ),
            )
        )


def _key(value: Any, field: str) -> str:
    return str(value.get(field) or "") if isinstance(value, Mapping) else ""


def _rounded(value: Any, digits: int) -> float | int | None:
    if value is None:
        return None
    return round(float(value), digits) if digits else round(float(value))


def _step_type(header: str) -> str:
    folded = unicodedata.normalize("NFKD", header.casefold())
    text = "".join(char for char in folded if not unicodedata.combining(char))
    if any(word in text for word in _COOLDOWN_WORDS):
        return "cooldown"
    return "warmup" if any(word in text for word in _WARMUP_WORDS) else "interval"


def _step_kind(key: str) -> dict[str, Any]:
    return {
        "stepTypeId": _STEP_TYPES[key],
        "stepTypeKey": key,
        "displayOrder": _STEP_TYPES[key],
    }


def _group(
    order: int, iterations: int, children: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": _step_kind("repeat"),
        "numberOfIterations": iterations,
        "workoutSteps": children,
        "endCondition": {
            "conditionTypeId": 7,
            "conditionTypeKey": "iterations",
            "displayOrder": 7,
            "displayable": False,
        },
        "endConditionValue": float(iterations),
        "smartRepeat": False,
    }


def _executable(
    order: int,
    number: int,
    step: Mapping[str, Any],
    step_type: str,
    targets: GarminRunTargets,
) -> dict[str, Any]:
    where = f"Schritt {number}"
    if step.get("ramp"):
        raise GarminRunMappingError(
            f"{where}: Rampen werden von Garmin-Trainings nicht unterstützt."
        )
    if "duration" in step:
        condition, value = (2, "time"), float(step["duration"])
    elif "distance" in step:
        condition, value = (3, "distance"), float(step["distance"])
    else:
        raise GarminRunMappingError(f"{where}: Dauer oder Distanz fehlt für Garmin.")
    kind = str(step.get("kind") or "")
    low, high = _range(
        where, kind, str(step.get("target") or "").strip().upper(), targets
    )
    key, target_id = _TARGETS[kind]
    # Pace is sent at the precision comparable_steps compares (0.001 m/s).
    digits = 3 if kind == "pace" else 0
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _step_kind(step_type),
        "endCondition": {
            "conditionTypeId": condition[0],
            "conditionTypeKey": condition[1],
            "displayOrder": condition[0],
            "displayable": True,
        },
        "endConditionValue": value,
        "targetType": {
            "workoutTargetTypeId": target_id,
            "workoutTargetTypeKey": key,
            "displayOrder": target_id,
        },
        "targetValueOne": round(low, digits),
        "targetValueTwo": round(high, digits),
        "zoneNumber": None,
    }


def _range(
    where: str, kind: str, text: str, targets: GarminRunTargets
) -> tuple[float, float]:
    """The absolute (lower, upper) bounds of a target: W, bpm or m/s."""
    if kind not in _TARGETS:
        raise GarminRunMappingError(
            f"{where}: Die Zielart '{kind}' wird nicht unterstützt."
        )
    if kind == "pace" and (pace := _PACE.fullmatch(text)):
        return _pace_range(where, pace)
    if absolute := _ABSOLUTE.fullmatch(text):
        if absolute["unit"] == _ABSOLUTE_UNITS.get(kind):
            return _bounds(absolute["low"], absolute["high"])
    elif zone := _ZONE.fullmatch(text):
        return _zone_range(where, kind, zone, targets)
    elif (percent := _PERCENT.fullmatch(text)) and "%" in text:
        reference = _reference(where, kind, percent["basis"], targets)
        low, high = _bounds(percent["low"], percent["high"])
        return low * reference / 100, high * reference / 100
    raise GarminRunMappingError(
        f"{where}: Das Ziel '{text}' wird für Garmin-Läufe nicht unterstützt."
    )


def _bounds(low: str, high: str | None) -> tuple[float, float]:
    first = float(low)
    second = float(high) if high is not None else first
    return min(first, second), max(first, second)


def _reference(
    where: str, kind: str, basis: str | None, targets: GarminRunTargets
) -> float:
    field = _PERCENT_BASES.get((kind, basis))
    if field is None:
        raise GarminRunMappingError(
            f"{where}: Die Prozentbasis {basis or 'ohne Angabe'} passt nicht zum Ziel ({kind})."
        )
    value = getattr(targets, field[0])
    if not value:
        raise GarminRunMappingError(
            f"{where}: Das relative Ziel braucht den Referenzwert {field[1]}, "
            "der nicht vorliegt; bitte einen absoluten Wert angeben."
        )
    return float(value)


def _pace_range(where: str, pace: re.Match[str]) -> tuple[float, float]:
    units = {pace["low_unit"], pace["high_unit"]} - {None}
    if len(units) != 1 or not units <= {"KM", "MI"}:
        raise GarminRunMappingError(
            f"{where}: Tempoziele brauchen für Garmin genau eine Einheit, /km oder /mi."
        )
    meters = 1000.0 if units == {"KM"} else _METERS_PER_MILE
    speeds = []
    for text in (pace["low"], pace["high"] or pace["low"]):
        minutes, seconds = text.split(":")
        total = int(minutes) * 60 + int(seconds)
        if total <= 0:
            raise GarminRunMappingError(f"{where}: Das Tempoziel muss positiv sein.")
        speeds.append(meters / total)
    return min(speeds), max(speeds)


def _zone_range(
    where: str, kind: str, zone: re.Match[str], targets: GarminRunTargets
) -> tuple[float, float]:
    limits = {
        "power": targets.power_limits,
        "hr": targets.hr_limits,
        "pace": targets.pace_limits,
    }[kind]
    if kind == "hr" and targets.hr_zone_basis:
        basis = float(targets.hr_zone_basis)
    else:
        basis = _reference(where, kind, _ZONE_BASES[kind], targets)
    first, last = sorted((int(zone["low"]), int(zone["high"] or zone["low"])))
    if not limits or first < 1 or last > len(limits) + 1:
        raise GarminRunMappingError(
            f"{where}: Die Zone Z{first if first < 1 else last} ist in den "
            "Zonengrenzen des Athleten nicht definiert."
        )
    low = ZONE_FLOOR_PERCENT if first == 1 else limits[first - 2]
    if last <= len(limits):
        return low * basis / 100, limits[last - 1] * basis / 100
    if kind == "hr" and targets.max_hr:
        return low * basis / 100, float(targets.max_hr)
    raise GarminRunMappingError(
        f"{where}: Die oberste Zone Z{last} hat keine Obergrenze; "
        "bitte einen konkreten Wert angeben."
    )
