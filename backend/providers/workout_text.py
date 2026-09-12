"""Validate the Coach's deliberately bounded Intervals.icu authoring syntax.

No prose-to-workout inference: missing targets and contradictory totals need a
Coach edit. Distance-step duration is left to the athlete's provider settings.
"""

import math
import re
from typing import Any


class WorkoutTextError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


_DISTANCE = re.compile(r"\d+(?:\.\d+)?(?P<unit>[a-z]+)")
_DISTANCE_UNITS = frozenset({"km", "mtr", "mi", "yd"})
_TIME_UNITS = frozenset("hms'\"")
_TARGET_PATTERNS = (
    re.compile(r"Z\d++(?:-Z\d++)?+(?:\s++(?:HR|Pace))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:\.\d++)?+%(?:\s++(?:HR|LTHR|Pace|FTP))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:\.\d++)?+-\d++(?:\.\d++)?+%(?:\s++(?:HR|LTHR|Pace|FTP))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:\.\d++)?+%-\d++(?:\.\d++)?+%(?:\s++(?:HR|LTHR|Pace|FTP))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:-\d++)?+(?:w|bpm)(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/(?:km|mi|100m|100y|500m|400m|250m))?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/km)?+-\d++:[0-5]\d(?:/km)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/mi)?+-\d++:[0-5]\d(?:/mi)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/100m)?+-\d++:[0-5]\d(?:/100m)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/100y)?+-\d++:[0-5]\d(?:/100y)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/500m)?+-\d++:[0-5]\d(?:/500m)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/400m)?+-\d++:[0-5]\d(?:/400m)?+\s++Pace(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/250m)?+-\d++:[0-5]\d(?:/250m)?+\s++Pace(?=$|\s)", re.IGNORECASE),
)


def _target_match(value: str, *, search: bool = False):
    for pattern in _TARGET_PATTERNS:
        match = pattern.search(value) if search else pattern.match(value)
        if match:
            return match
    return None


def _distance_match(value: str):
    match = _DISTANCE.fullmatch(value)
    return match if match and match["unit"] in _DISTANCE_UNITS else None


def _is_time(value: str) -> bool:
    return bool(_time_parts(value))


def _time_parts(value: str) -> list[tuple[str, str]] | None:
    position = 0
    parts = []
    while position < len(value):
        parsed = _read_time_part(value, position)
        if parsed is None:
            return None
        position, amount, unit = parsed
        parts.append((amount, unit))
    return parts or None


def _read_time_part(value: str, position: int) -> tuple[int, str, str] | None:
    amount_start = position
    while position < len(value) and value[position].isdecimal():
        position += 1
    if position == amount_start:
        return None
    if position < len(value) and value[position] == ".":
        position += 1
        fraction_start = position
        while position < len(value) and value[position].isdecimal():
            position += 1
        if position == fraction_start:
            return None
    if position >= len(value) or value[position] not in _TIME_UNITS:
        return None
    return position + 1, value[amount_start:position], value[position]


def _normalize_zone(match):
    end = match.group("end")
    suffix = match.group("kind") or ""
    return "Z" + match.group("start") + ("-Z" + end if end else "") + (" " + suffix if suffix else "")


def _canonical_zone_line(line: str, pattern: re.Pattern[str]) -> str:
    stripped = line.lstrip(" \t")
    if not stripped.startswith("- "):
        return line
    cursor = len(line) - len(stripped) + 1
    while cursor < len(line) and line[cursor] in " \t":
        cursor += 1
    quantity_start = cursor
    while cursor < len(line) and line[cursor] not in " \t":
        cursor += 1
    if cursor == quantity_start:
        return line
    while cursor < len(line) and line[cursor] in " \t":
        cursor += 1
    if cursor == len(line):
        return line
    target = line[cursor:]
    match = pattern.match(target)
    if not match:
        return line
    prefix = match["ramp"] or ""
    return line[:cursor] + prefix + _normalize_zone(match) + target[match.end():]


def canonical_workout_zones(description: str, *, endurance: bool = True) -> str:
    """Normalize explicit zone notation only, never infer effort from prose."""
    if not endurance:
        return description
    pattern = re.compile(
        r"^(?P<ramp>ramp\s++)?+(?:Zone\s*+|Z\s*+)(?P<start>[1-9])"
        r"(?:\s*[-\u2013\u2014]\s*(?:Zone\s*|Z\s*)?(?P<end>[1-9]))?"
        r"(?:\s++(?P<kind>HR|Pace))?(?=$|\s)", re.IGNORECASE,
    )
    return "\n".join(_canonical_zone_line(line, pattern) for line in description.split("\n"))


def _workout_quantity(line: str, number: int) -> tuple[str, str]:
    step_text = line[1:].lstrip(" \t")
    separator = next((index for index, character in enumerate(step_text) if character in " \t"), -1)
    quantity = (step_text[:separator], step_text[separator:].lstrip(" \t")) if separator > 0 else None
    if not quantity or not (_is_time(quantity[0]) or _distance_match(quantity[0])):
        raise WorkoutTextError("invalid_workout_step", f"Workout-Zeile {number}: Dauer oder Distanz in Workout-Syntax angeben.")
    return quantity


def _workout_target(rest: str, number: int, target: str) -> tuple[str, str, bool]:
    ramp = rest[:4].casefold() == "ramp" and len(rest) > 4 and rest[4] in " \t"
    if ramp:
        rest = rest[4:].lstrip(" \t")
    intensity = _target_match(rest)
    if not intensity:
        raise WorkoutTextError("missing_workout_target", f"Workout-Zeile {number}: Auswertbares Intensitaetsziel fehlt.")
    cue = re.sub(r"[(),;]", " ", rest[intensity.end():])
    if _target_match(cue, search=True):
        raise WorkoutTextError("ambiguous_workout_target", f"Workout-Zeile {number}: Mehrere Intensitaetsziele im selben Schritt.")
    parsed = intensity[0].upper()
    kind = "PACE" if "PACE" in parsed else "HR" if re.search(r"HR|BPM", parsed) else "POWER"
    if target in {"POWER", "HR", "PACE"} and target != kind:
        raise WorkoutTextError("workout_target_mismatch", f"Workout-Zeile {number}: Schrittziel {kind} passt nicht zum Einheitenziel {target}.")
    return parsed, kind, ramp


def _workout_amount(value: str, number: int) -> dict:
    distance_match = _distance_match(value)
    if distance_match:
        amount_match = re.match(r"\d+(?:\.\d+)?", value)
        amount = float(amount_match[0])
        if not math.isfinite(amount) or amount <= 0:
            raise WorkoutTextError("invalid_workout_step", "Eine Trainingsdistanz muss positiv sein.")
        unit = value[len(amount_match[0]):]
        return {"distance": amount * {"km": 1000, "mtr": 1, "mi": 1609.344, "yd": 0.9144}[unit]}
    parts = _time_parts(value)
    seconds = sum(float(amount) * {"h": 3600, "m": 60, "s": 1, "'": 60, '"': 1}[unit] for amount, unit in parts or ())
    if not math.isfinite(seconds) or seconds <= 0:
        raise WorkoutTextError("invalid_workout_step", "Eine Trainingsdauer muss positiv sein.")
    return {"duration": seconds}


def _parse_workout_step(line: str, number: int, target: str) -> dict:
    value, rest = _workout_quantity(line, number)
    parsed_target, kind, ramp = _workout_target(rest, number, target)
    return {"kind": kind.lower(), "target": parsed_target, "ramp": ramp, **_workout_amount(value, number)}


def _repeat_header(line: str, repeat_pending: bool, previous_step: bool) -> tuple[int, bool, bool]:
    header = re.search(r"\b(\d+)x$", line)
    if not header:
        if repeat_pending or previous_step:
            raise WorkoutTextError("invalid_workout_repeat", "Hinweise und neue Abschnitte durch eine Leerzeile von Trainingsschritten trennen.")
        return 1, False, False
    repeat = int(header[1])
    if repeat_pending or previous_step or not 1 <= repeat <= 100:
        raise WorkoutTextError("invalid_workout_repeat", "Wiederholungsbloecke mit Leerzeilen trennen.")
    return repeat, True, False


def structured_steps(description: str, target: str = "AUTO") -> list[dict]:
    """Return expanded steps for comparison with the provider's parsed reply."""
    result, block = [], []
    repeat, repeat_pending, previous_step = 1, False, False
    for number, raw_line in enumerate(description.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            if repeat_pending:
                raise WorkoutTextError("invalid_workout_repeat", "Nach einer Wiederholung muessen direkt Trainingsschritte folgen.")
            result.extend(block * repeat)
            block, repeat, previous_step = [], 1, False
        elif line.startswith("-"):
            block.append(_parse_workout_step(line, number, target))
            repeat_pending, previous_step = False, True
        else:
            repeat, repeat_pending, previous_step = _repeat_header(line, repeat_pending, previous_step)
    if repeat_pending:
        raise WorkoutTextError("invalid_workout_repeat", "Wiederholungsblock ohne Trainingsschritte.")
    if not block and not result:
        raise WorkoutTextError("missing_workout_steps", "Ausdauer-Einheit ohne auswertbare Trainingsschritte.")
    result.extend(block * repeat)
    if len(result) > 5000:
        raise WorkoutTextError("invalid_workout_repeat", "Zu viele Trainingsschritte; Einheit in kleinere Bloecke aufteilen.")
    return result


def structured_duration(description: str, target: str = "AUTO") -> tuple[float, bool]:
    steps = structured_steps(description, target)
    return sum(step.get("duration", 0) for step in steps), any("distance" in step for step in steps)

def _readback_failure() -> None:
    raise WorkoutTextError("intervals_workout_verification_failed", "Intervals.icu hat die Einheit nicht korrekt bestaetigt.")


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _flatten_steps(steps: Any, depth: int = 0) -> list[dict]:
    if not isinstance(steps, list) or not steps or depth > 3:
        _readback_failure()
    flat = []
    for step in steps:
        if not isinstance(step, dict):
            _readback_failure()
        if "steps" in step:
            reps = step.get("reps", 1)
            if not isinstance(reps, int) or not 1 <= reps <= 100:
                _readback_failure()
            flat.extend(_flatten_steps(step["steps"], depth + 1) * reps)
        else:
            flat.append(step)
        if len(flat) > 5000:
            _readback_failure()
    return flat


def _expected_intensity(wanted: dict, intensity: dict) -> tuple[list[float], str]:
    text = wanted["target"]
    if ":" in text:
        values = [int(m) * 60 + int(s) for m, s in re.findall(r"(\d{1,3}):([0-5]\d)", text)]
        denominators = re.findall(r"/(KM|MI|100M|100Y|500M|400M|250M)", text)
        units = "secs/" + denominators[0].lower() if denominators else str(intensity.get("units") or "")
        if not units.startswith("secs/") or len(set(denominators)) > 1:
            _readback_failure()
        return values, units
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
    if text.startswith("Z"):
        units = wanted["kind"] + "_zone"
    elif "%" in text:
        units = "%lthr" if "LTHR" in text else {"power": "%ftp", "hr": "%hr", "pace": "%pace"}[wanted["kind"]]
    else:
        units = "bpm" if "BPM" in text else "w"
    return values, units


def _verify_step(wanted: dict, got: Any) -> None:
    if not isinstance(got, dict):
        _readback_failure()
    quantity = "distance" if "distance" in wanted else "duration"
    if not _numeric(got.get(quantity)) or abs(got[quantity] - wanted[quantity]) > 1:
        _readback_failure()
    if bool(got.get("ramp")) != wanted["ramp"]:
        _readback_failure()
    intensity = got.get(wanted["kind"])
    if not isinstance(intensity, dict):
        _readback_failure()
    values, units = _expected_intensity(wanted, intensity)
    if intensity.get("units") != units:
        _readback_failure()
    keys = ("value",) if len(values) == 1 else ("start", "end")
    if len(values) != len(keys) or any(not _numeric(intensity.get(key)) or abs(intensity[key] - value) > 0.01 for key, value in zip(keys, values)):
        _readback_failure()


def _verify_totals(doc: dict, remote: dict, actual: list[dict]) -> None:
    durations = [step.get("duration") for step in actual]
    if any(not _numeric(value) or value <= 0 for value in durations):
        _readback_failure()
    total = sum(durations)
    tolerance = max(1, len(actual))
    if not _numeric(doc.get("duration")) or abs(doc["duration"] - total) > tolerance:
        _readback_failure()
    if not _numeric(remote.get("moving_time")) or abs(remote["moving_time"] - total) > tolerance:
        _readback_failure()
    if not _numeric(remote.get("icu_training_load")) or remote["icu_training_load"] <= 0:
        _readback_failure()


def verify_workout_readback(description: str, remote: dict) -> None:
    """Require provider-generated steps, targets and load, not just HTTP 200."""
    if not isinstance(remote, dict):
        _readback_failure()
    doc = remote.get("workout_doc")
    if not isinstance(doc, dict):
        _readback_failure()
    actual = _flatten_steps(doc.get("steps"))
    expected = structured_steps(description)
    if len(actual) != len(expected):
        _readback_failure()
    for wanted, got in zip(expected, actual):
        _verify_step(wanted, got)
    _verify_totals(doc, remote, actual)
