"""Wahoo plan JSON for one local library workout.

Provider-owned and pure: maps a canonical sport and the expanded structured
steps of a local workout onto the Wahoo plan file (``plan.json``, version
1.0.0, https://cloud-api.wahooligan.com/docs/plan-json-format.pdf). Parsing the
workout text and resolving the stored sport token stay with the caller, so this
module only sees canonical values and plain step dictionaries.

Nothing is dropped silently. A sport, step or target the plan format cannot
express raises ``WahooPlanMappingError`` with a message that names the
unsupported part, and the caller reports it for that one workout.

Supported: biking and running plans; time and distance steps; absolute power
(watts), heart rate (bpm) and pace (min/km, min/mi); relative targets (percent
of FTP, maximum or threshold heart rate, threshold speed) when the matching
athlete reference is supplied, because Wahoo resolves them against the plan
header. Not supported: zones (they need the athlete's zone model), ramps,
other sports and pace units other than km and mi.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.canonical.vocabulary import Environment, Sport
from backend.errors import AppError

PLAN_SCHEMA_VERSION: Final = "1.0.0"
MAX_PLAN_NAME_LENGTH: Final = 200
MAX_PLAN_DESCRIPTION_LENGTH: Final = 5000
UNSUPPORTED_PLAN_REASON: Final = "wahoo_plan_unsupported"

_FAMILY_BIKING: Final = 0
_FAMILY_RUNNING: Final = 1
_LOCATION_INDOOR: Final = 0
_LOCATION_OUTDOOR: Final = 1
_FAMILIES: Final = {Sport.RIDE: _FAMILY_BIKING, Sport.RUN: _FAMILY_RUNNING}
_INDOOR_ENVIRONMENTS: Final = frozenset({Environment.INDOOR, Environment.VIRTUAL})
_METERS_PER_MILE: Final = 1609.344

_ZONE = re.compile(r"Z\d+(?:-Z\d+)?(?:\s+(?:HR|PACE))?")
_ABSOLUTE = re.compile(r"(?P<low>\d+)(?:-(?P<high>\d+))?(?P<unit>W|BPM)")
_PERCENT = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)%?(?:-(?P<high>\d+(?:\.\d+)?)%)?"
    r"(?:\s+(?P<basis>HR|LTHR|PACE|FTP))?"
)
_PACE = re.compile(
    r"(?P<low>\d+:[0-5]\d)(?:/(?P<low_unit>KM|MI|[0-9]+[MY]))?"
    r"(?:-(?P<high>\d+:[0-5]\d)(?:/(?P<high_unit>KM|MI|[0-9]+[MY]))?)?\s+PACE"
)


class WahooPlanMappingError(AppError):
    """A local workout the Wahoo plan format cannot represent."""

    def __init__(self, message: str) -> None:
        super().__init__(422, message, reason=UNSUPPORTED_PLAN_REASON)


@dataclass(frozen=True, slots=True)
class WahooPlanReferences:
    """Athlete values that Wahoo needs to resolve relative targets.

    Each is optional. A relative step whose reference is missing is rejected
    instead of being exported against a guessed value.
    """

    ftp: int | None = None
    max_hr: int | None = None
    threshold_hr: int | None = None
    threshold_speed: float | None = None

    def header(self) -> dict[str, int | float]:
        """Return the header fields for the references that are set."""
        values: dict[str, int | float | None] = {
            "ftp": self.ftp,
            "max_hr": self.max_hr,
            "threshold_hr": self.threshold_hr,
            "threshold_speed": self.threshold_speed,
        }
        return {key: value for key, value in values.items() if value}


def wahoo_plan(
    *,
    name: str,
    description: str,
    sport: Sport,
    environment: Environment,
    steps: Sequence[Mapping[str, Any]],
    references: WahooPlanReferences | None = None,
) -> dict[str, Any]:
    """Return the Wahoo plan document for one workout or raise a mapping error."""
    family = _FAMILIES.get(sport)
    if family is None:
        raise WahooPlanMappingError(
            "Wahoo-Pläne unterstützen nur Rad- und Laufeinheiten; "
            f"die Sportart '{sport.value}' kann nicht exportiert werden."
        )
    if not steps:
        raise WahooPlanMappingError(
            "Die Einheit hat keine strukturierten Trainingsschritte für Wahoo."
        )
    resolved = references or WahooPlanReferences()
    intervals = [
        _interval(number, step, family, resolved)
        for number, step in enumerate(steps, 1)
    ]
    header: dict[str, Any] = {
        "name": str(name or "Coach workout")[:MAX_PLAN_NAME_LENGTH],
        "version": PLAN_SCHEMA_VERSION,
        "workout_type_family": family,
        "workout_type_location": _LOCATION_INDOOR
        if environment in _INDOOR_ENVIRONMENTS
        else _LOCATION_OUTDOOR,
        **resolved.header(),
    }
    text = str(description or "")[:MAX_PLAN_DESCRIPTION_LENGTH]
    if text:
        header["description"] = text
    return {"header": header, "intervals": intervals}


def _interval(
    number: int,
    step: Mapping[str, Any],
    family: int,
    references: WahooPlanReferences,
) -> dict[str, Any]:
    if step.get("ramp"):
        raise WahooPlanMappingError(
            f"Schritt {number}: Rampen werden von Wahoo-Plänen nicht unterstützt."
        )
    interval: dict[str, Any] = {"intensity_type": "active"}
    if "duration" in step:
        interval["exit_trigger_type"] = "time"
        interval["exit_trigger_value"] = _number(step["duration"])
    elif "distance" in step:
        interval["exit_trigger_type"] = "distance"
        interval["exit_trigger_value"] = _number(step["distance"])
    else:
        raise WahooPlanMappingError(
            f"Schritt {number}: Dauer oder Distanz fehlt für Wahoo."
        )
    interval["targets"] = [_target(number, step, family, references)]
    return interval


def _number(value: Any) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _target(
    number: int,
    step: Mapping[str, Any],
    family: int,
    references: WahooPlanReferences,
) -> dict[str, Any]:
    kind = str(step.get("kind") or "")
    text = str(step.get("target") or "").strip().upper()
    where = f"Schritt {number}"
    if _ZONE.fullmatch(text):
        raise WahooPlanMappingError(
            f"{where}: Zonenziele ({text}) werden von Wahoo-Plänen nicht "
            "unterstützt; bitte konkrete Werte angeben."
        )
    if kind == "power":
        if family != _FAMILY_BIKING:
            raise WahooPlanMappingError(
                f"{where}: Leistungsziele sind in Wahoo-Laufplänen nicht unterstützt."
            )
        return _power_target(where, text, references)
    if kind == "hr":
        return _heart_rate_target(where, text, references)
    if kind == "pace":
        if family != _FAMILY_RUNNING:
            raise WahooPlanMappingError(
                f"{where}: Tempoziele sind in Wahoo-Radplänen nicht unterstützt."
            )
        return _pace_target(where, text, references)
    raise WahooPlanMappingError(
        f"{where}: Das Zielformat '{text}' wird nicht unterstützt."
    )


def _bounds(low: str, high: str | None, scale: float = 1.0) -> tuple[float, float]:
    first = float(low) / scale
    second = float(high) / scale if high is not None else first
    return min(first, second), max(first, second)


def _entry(kind: str, low: float, high: float) -> dict[str, Any]:
    return {"type": kind, "low": _number(low), "high": _number(high)}


def _require(where: str, value: float | None, label: str) -> None:
    if not value:
        raise WahooPlanMappingError(
            f"{where}: Das relative Ziel braucht den Referenzwert {label}, "
            "der nicht vorliegt; bitte einen absoluten Wert angeben."
        )


def _power_target(
    where: str, text: str, references: WahooPlanReferences
) -> dict[str, Any]:
    absolute = _ABSOLUTE.fullmatch(text)
    if absolute and absolute["unit"] == "W":
        return _entry("watts", *_bounds(absolute["low"], absolute["high"]))
    percent = _PERCENT.fullmatch(text)
    if percent and "%" in text and percent["basis"] in {None, "FTP"}:
        _require(where, references.ftp, "FTP")
        return _entry("ftp", *_bounds(percent["low"], percent["high"], 100.0))
    raise WahooPlanMappingError(
        f"{where}: Das Leistungsziel '{text}' wird von Wahoo-Plänen nicht unterstützt."
    )


def _heart_rate_target(
    where: str, text: str, references: WahooPlanReferences
) -> dict[str, Any]:
    absolute = _ABSOLUTE.fullmatch(text)
    if absolute and absolute["unit"] == "BPM":
        return _entry("hr", *_bounds(absolute["low"], absolute["high"]))
    percent = _PERCENT.fullmatch(text)
    if percent and "%" in text and percent["basis"] in {"HR", "LTHR"}:
        if percent["basis"] == "LTHR":
            _require(where, references.threshold_hr, "Schwellenpuls")
            kind = "threshold_hr"
        else:
            _require(where, references.max_hr, "maximale Herzfrequenz")
            kind = "max_hr"
        return _entry(kind, *_bounds(percent["low"], percent["high"], 100.0))
    raise WahooPlanMappingError(
        f"{where}: Das Herzfrequenzziel '{text}' wird von Wahoo-Plänen nicht "
        "unterstützt."
    )


def _pace_speed(where: str, value: str, unit: str) -> float:
    minutes, seconds = value.split(":")
    total = int(minutes) * 60 + int(seconds)
    if total <= 0:
        raise WahooPlanMappingError(f"{where}: Das Tempoziel muss positiv sein.")
    meters = 1000.0 if unit == "KM" else _METERS_PER_MILE
    return meters / total


def _pace_target(
    where: str, text: str, references: WahooPlanReferences
) -> dict[str, Any]:
    pace = _PACE.fullmatch(text)
    if pace:
        unit = pace["high_unit"] or pace["low_unit"]
        if unit not in {"KM", "MI"}:
            raise WahooPlanMappingError(
                f"{where}: Tempoziele brauchen für Wahoo die Einheit /km oder /mi."
            )
        low = _pace_speed(where, pace["low"], unit)
        high = _pace_speed(where, pace["high"] or pace["low"], unit)
        return _entry("speed", min(low, high), max(low, high))
    percent = _PERCENT.fullmatch(text)
    if percent and "%" in text and percent["basis"] == "PACE":
        _require(where, references.threshold_speed, "Schwellentempo")
        return _entry(
            "threshold_speed", *_bounds(percent["low"], percent["high"], 100.0)
        )
    raise WahooPlanMappingError(
        f"{where}: Das Tempoziel '{text}' wird von Wahoo-Plänen nicht unterstützt."
    )
