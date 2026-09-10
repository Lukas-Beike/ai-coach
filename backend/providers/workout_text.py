"""Validate the Coach's deliberately bounded Intervals.icu authoring syntax.

No prose-to-workout inference: missing targets and contradictory totals need a
Coach edit. Distance-step duration is left to the athlete's provider settings.
"""

import math
import re


class WorkoutTextError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


_DISTANCE = re.compile(r"\d+(?:\.\d+)?(?P<unit>[a-z]+)")
_DISTANCE_UNITS = frozenset({"km", "mtr", "mi", "yd"})
_TIME_PART = re.compile(r"(\d++(?:\.\d++)?+)([hms'\"])")
_TARGET_PATTERNS = (
    re.compile(r"Z\d++(?:-Z\d++)?+(?:\s++(?:HR|Pace))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:\.\d++)?+(?:%?+-\d++(?:\.\d++)?+)?+%(?:\s++(?:HR|LTHR|Pace|FTP))?+(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++(?:-\d++)?+(?:w|bpm)(?=$|\s)", re.IGNORECASE),
    re.compile(r"\d++:[0-5]\d(?:/(?:km|mi|100m|100y|500m|400m|250m))?+(?:-\d++:[0-5]\d(?:/(?:km|mi|100m|100y|500m|400m|250m))?+\s++Pace)?+(?=$|\s)", re.IGNORECASE),
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
    position = 0
    while position < len(value):
        match = _TIME_PART.match(value, position)
        if not match:
            return False
        position = match.end()
    return bool(value)


def canonical_workout_zones(description: str, *, endurance: bool = True) -> str:
    """Normalize explicit zone notation only, never infer effort from prose.

    The Coach selects the intensity semantically. This serializer tolerates
    equivalent spellings in its output without changing targets or cues.
    """
    def zone(match):
        end = match.group("end")
        suffix = match.group("kind") or ""
        return "Z" + match.group("start") + ("-Z" + end if end else "") + (" " + suffix if suffix else "")

    pattern = re.compile(
        r"^(?P<ramp>ramp\s++)?+(?:Zone\s*+|Z\s*+)(?P<start>[1-9])"
        r"(?:\s*[-–—]\s*(?:Zone\s*|Z\s*)?(?P<end>[1-9]))?"
        r"(?:\s++(?P<kind>HR|Pace))?(?=$|\s)", re.IGNORECASE,
    )
    if not endurance:
        return description
    normalized = []
    for line in description.split("\n"):
        stripped = line.lstrip(" \t")
        if not stripped.startswith("- "):
            normalized.append(line)
            continue
        # Only the target immediately following the first duration/distance is
        # executable workout syntax. Cues later in the line must remain prose.
        cursor = len(line) - len(stripped) + 1
        while cursor < len(line) and line[cursor] in " \t":
            cursor += 1
        quantity_start = cursor
        while cursor < len(line) and line[cursor] not in " \t":
            cursor += 1
        if cursor == quantity_start:
            normalized.append(line)
            continue
        while cursor < len(line) and line[cursor] in " \t":
            cursor += 1
        if cursor == len(line):
            normalized.append(line)
            continue
        step_prefix = line[:cursor]
        target = line[cursor:]
        match = pattern.match(target)
        if not match:
            normalized.append(line)
            continue
        prefix = match["ramp"] or ""
        normalized.append(step_prefix + prefix + zone(match) + target[match.end():])
    return "\n".join(normalized)


def structured_steps(description: str, target: str = "AUTO") -> list[dict]:
    """Return expanded steps for comparison with the provider's parsed reply."""
    result = []
    block = []
    step_count = 0
    repeat = 1
    repeat_pending = False
    previous_step = False
    for number, raw in enumerate(description.splitlines(), 1):
        line = raw.strip()
        if not line:
            if repeat_pending:
                raise WorkoutTextError("invalid_workout_repeat", "Nach einer Wiederholung muessen direkt Trainingsschritte folgen.")
            result.extend(block * repeat)
            block = []
            repeat = 1
            previous_step = False
            continue
        if not line.startswith("-"):
            header = re.search(r"\b(\d+)x$", line)
            if header:
                if repeat_pending or previous_step or not 1 <= int(header[1]) <= 100:
                    raise WorkoutTextError("invalid_workout_repeat", "Wiederholungsbloecke mit Leerzeilen trennen; z.B. '2x' direkt vor den Schritten.")
                repeat = int(header[1])
                repeat_pending = True
            elif repeat_pending or previous_step:
                raise WorkoutTextError("invalid_workout_repeat", "Hinweise und neue Abschnitte durch eine Leerzeile von Trainingsschritten trennen.")
            continue
        step_text = line[1:].lstrip(" \t") if line.startswith("-") else ""
        separator = next((index for index, character in enumerate(step_text) if character in " \t"), -1)
        quantity = (step_text[:separator], step_text[separator:].lstrip(" \t")) if separator > 0 else None
        if not quantity or not (_is_time(quantity[0]) or _distance_match(quantity[0])):
            raise WorkoutTextError("invalid_workout_step", f"Workout-Zeile {number}: Dauer oder Distanz in Workout-Syntax angeben, z.B. '- 15m 50-70%' oder '- 6km Z1 HR'. Hinweise ohne '- ' schreiben.")
        value, rest = quantity
        ramp_prefix = rest[:4].casefold() == "ramp" and len(rest) > 4 and rest[4] in " \t"
        ramp = bool(ramp_prefix)
        if ramp_prefix:
            rest = rest[4:].lstrip(" \t")
        intensity = _target_match(rest)
        if not intensity:
            raise WorkoutTextError("missing_workout_target", f"Workout-Zeile {number}: Auswertbares Intensitaetsziel fehlt. Nutze z.B. '50-70%', 'Z1 HR' oder 'Z2 Pace'; Freitext wie 'locker' reicht nicht.")
        cue = re.sub(r"[(),;]", " ", rest[intensity.end():])
        if _target_match(cue, search=True):
            raise WorkoutTextError("ambiguous_workout_target", f"Workout-Zeile {number}: Mehrere Intensitaetsziele im selben Schritt. Nur ein Ziel angeben; umgerechnete Wattwerte und alternative Ziele als separaten Absatz ohne '- ' schreiben.")
        parsed_target = intensity[0].upper()
        if "PACE" in parsed_target:
            kind = "PACE"
        elif re.search(r"HR|BPM", parsed_target):
            kind = "HR"
        else:
            kind = "POWER"
        if target in {"POWER", "HR", "PACE"} and target != kind:
            raise WorkoutTextError("workout_target_mismatch", f"Workout-Zeile {number}: Schrittziel {kind} passt nicht zum Einheitenziel {target}. Ziel oder Schritt korrigieren; fuer gemischte Ziele AUTO verwenden.")
        expected = {"kind": kind.lower(), "target": parsed_target, "ramp": ramp}
        if _distance_match(value):
            amount_match = re.match(r"\d+(?:\.\d+)?", value)
            distance = float(amount_match[0])
            if not math.isfinite(distance) or distance <= 0:
                raise WorkoutTextError("invalid_workout_step", "Eine Trainingsdistanz muss positiv sein.")
            amount = amount_match[0]
            unit = value[len(amount):]
            expected["distance"] = float(amount) * {"km": 1000, "mtr": 1, "mi": 1609.344, "yd": 0.9144}[unit]
        else:
            seconds = sum(float(amount) * {"h": 3600, "m": 60, "s": 1, "'": 60, '"': 1}[unit] for amount, unit in _TIME_PART.findall(value))
            if not math.isfinite(seconds) or seconds <= 0:
                raise WorkoutTextError("invalid_workout_step", "Eine Trainingsdauer muss positiv sein.")
            expected["duration"] = seconds
        block.append(expected)
        step_count += 1
        previous_step = True
        repeat_pending = False
    if repeat_pending:
        raise WorkoutTextError("invalid_workout_repeat", "Wiederholungsblock ohne Trainingsschritte.")
    if not step_count:
        raise WorkoutTextError("missing_workout_steps", "Ausdauer-Einheit ohne auswertbare Trainingsschritte. Beschreibung als Intervals.icu Workout-Text mit '- Dauer Ziel' je Schritt schreiben; Fliesstext allein erzeugt keine Belastung.")
    result.extend(block * repeat)
    if len(result) > 5000:
        raise WorkoutTextError("invalid_workout_repeat", "Zu viele Trainingsschritte; Einheit in kleinere Bloecke aufteilen.")
    return result


def structured_duration(description: str, target: str = "AUTO") -> tuple[float, bool]:
    steps = structured_steps(description, target)
    return sum(step.get("duration", 0) for step in steps), any("distance" in step for step in steps)


def verify_workout_readback(description: str, remote: dict) -> None:
    """Require provider-generated steps, targets and load, not just HTTP 200.

    Source: https://forum.intervals.icu/t/downloading-planned-workouts-from-the-api/93737
    Only description is sent; workout_doc must have been generated by Intervals.
    """
    def fail():
        raise WorkoutTextError("intervals_workout_verification_failed", "Intervals.icu hat die Einheit gespeichert, aber Schritte, Ziele, Dauer oder Belastung nicht korrekt bestaetigt. Synchronisation bleibt fehlerhaft. Workout-Text und Sport-/Zoneneinstellungen in Intervals.icu pruefen und erneut synchronisieren.")

    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def flatten(steps, depth=0):
        if not isinstance(steps, list) or not steps or depth > 3:
            fail()
        flat = []
        for step in steps:
            if not isinstance(step, dict):
                fail()
            if "steps" in step:
                reps = step.get("reps", 1)
                if not isinstance(reps, int) or not 1 <= reps <= 100:
                    fail()
                flat.extend(flatten(step["steps"], depth + 1) * reps)
            else:
                flat.append(step)
            if len(flat) > 5000:
                fail()
        return flat

    if not isinstance(remote, dict):
        fail()
    doc = remote.get("workout_doc")
    if not isinstance(doc, dict):
        fail()
    actual = flatten(doc.get("steps"))
    expected = structured_steps(description)
    if len(actual) != len(expected):
        fail()
    for wanted, got in zip(expected, actual):
        quantity = "distance" if "distance" in wanted else "duration"
        if not numeric(got.get(quantity)) or abs(got[quantity] - wanted[quantity]) > 1:
            fail()
        if bool(got.get("ramp")) != wanted["ramp"]:
            fail()
        intensity = got.get(wanted["kind"])
        if not isinstance(intensity, dict):
            fail()
        text = wanted["target"]
        if ":" in text:
            values = [int(m) * 60 + int(s) for m, s in re.findall(r"(\d{1,3}):([0-5]\d)", text)]
            denominators = re.findall(r"/(KM|MI|100M|100Y|500M|400M|250M)", text)
            units = "secs/" + denominators[0].lower() if denominators else str(intensity.get("units") or "")
            if not units.startswith("secs/") or len(set(denominators)) > 1:
                fail()
        else:
            values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
            if text.startswith("Z"):
                units = wanted["kind"] + "_zone"
            elif "%" in text:
                units = "%lthr" if "LTHR" in text else {"power": "%ftp", "hr": "%hr", "pace": "%pace"}[wanted["kind"]]
            else:
                units = "bpm" if "BPM" in text else "w"
        if intensity.get("units") != units:
            fail()
        keys = ("value",) if len(values) == 1 else ("start", "end")
        if len(values) != len(keys):
            fail()
        if any(not numeric(intensity.get(key)) or abs(intensity[key] - value) > 0.01 for key, value in zip(keys, values)):
            fail()
    durations = [step.get("duration") for step in actual]
    if any(not numeric(value) or value <= 0 for value in durations):
        fail()
    total = sum(durations)
    if not numeric(doc.get("duration")) or abs(doc["duration"] - total) > max(1, len(actual)):
        fail()
    if not numeric(remote.get("moving_time")) or abs(remote["moving_time"] - total) > max(1, len(actual)):
        fail()
    if not numeric(remote.get("icu_training_load")) or remote["icu_training_load"] <= 0:
        fail()
