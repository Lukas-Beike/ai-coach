"""Garmin strength workout document built from a local ``strength_structure``.

Pure mapping, no I/O. Exercise names resolve against the ``garminconnect``
exercise catalogue: an explicit catalogue name first, then the exercise name
itself, then a small German/English alias list. Garmin stores an unknown
category or exercise name as a blank step without an error, so a structure with
any unresolved exercise is never turned into a workout. The document follows
the shape of ``garminconnect.workout.create_strength_set`` (a repeat group per
exercise with a reps step and a timed rest), built as plain JSON so the
optional pydantic models of the SDK are not needed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

try:
    from garminconnect import exercises as _catalogue
except ImportError:  # Optional dependency for installations without Garmin enabled.
    _catalogue = None  # type: ignore[assignment]

MAX_SUGGESTIONS: Final = 5
NO_STRUCTURE_MESSAGE: Final = "Keine Kraftstruktur – nicht an Garmin gesendet."
_NAME_LIMIT: Final = 80
_NOTE_LIMIT: Final = 100
_DESCRIPTION_LIMIT: Final = 1000
STRENGTH_SPORT: Final = {
    "sportTypeId": 5,
    "sportTypeKey": "strength_training",
    "displayOrder": 5,
}
_WARMUP_STEP: Final = {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1}
_INTERVAL_STEP: Final = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_REST_STEP: Final = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
_REPEAT_STEP: Final = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
_REPS_END: Final = {
    "conditionTypeId": 10,
    "conditionTypeKey": "reps",
    "displayOrder": 10,
    "displayable": True,
}
_TIME_END: Final = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
_ITERATIONS_END: Final = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
_NO_TARGET: Final = {
    "workoutTargetTypeId": 1,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
# Garmin stores weightValue in grams tagged with the kilogram unit.
_WEIGHT_UNIT: Final = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}

# Garmin catalogue display name -> folded local names. Only common lifts whose
# German or short English name has one obvious catalogue entry.
_ALIAS_GROUPS: Final = {
    "Barbell Back Squat": ("kniebeuge", "kniebeugen"),
    "Barbell Front Squat": ("frontkniebeuge", "front squat"),
    "Goblet Squat": ("goblet squat",),
    "Barbell Deadlift": ("kreuzheben",),
    "Romanian Deadlift": ("rumanisches kreuzheben", "rdl"),
    "Barbell Bench Press": ("bankdrucken",),
    "Incline Barbell Bench Press": (
        "schragbankdrucken",
        "schragbankdrucken langhantel",
        "incline bench press",
        "incline press",
    ),
    "Incline Dumbbell Bench Press": (
        "schragbankdrucken kurzhantel",
        "kurzhantel schragbankdrucken",
    ),
    "Alternating Dumbbell Lunge": (
        "ausfallschritt",
        "ausfallschritte",
    ),
    "Dumbbell Bulgarian Split Squat": (
        "bulgarian split squat",
        "bulgarische kniebeuge",
    ),
    "Calf Raise": ("wadenheben", "calf raise"),
    "Leg Press": ("beinpresse", "leg press"),
    "Leg Curl": ("beinbeuger", "leg curl"),
    "Barbell Hip Thrust with Bench": ("hip thrust",),
    "Pull-up": ("klimmzuge", "klimmzug", "pull-up", "pull-ups"),
    "Push-up": ("liegestutze", "liegestutz", "push-up", "push-ups"),
    "Bent-over Row with Barbell": ("rudern", "langhantelrudern", "bent-over row"),
    "Barbell Shoulder Press": ("schulterdrucken",),
    "Barbell Overhead Press": ("overhead press",),
    "Lat Pull-down": ("latziehen", "lat pulldown", "latzug"),
    "Hyperextension": ("ruckenstrecker",),
    "Body-weight Dip": ("dip", "barrenstutz"),
    "Seated Cable Row": ("rudern im sitzen", "kabelrudern", "seated row"),
    "V-grip Cable Row": (
        "enges rudern im sitzen",
        "enges rudern",
        "rudern im sitzen eng",
        "close-grip seated cable row",
    ),
    "Lateral Raise": ("seitheben", "seitenheben"),
    "Cable Biceps Curl": (
        "bizeps am seilzug",
        "bizepscurl am seilzug",
        "bizeps am kabelzug",
        "cable curl",
    ),
    "Dumbbell Biceps Curl": ("bizepscurl", "bizeps curl", "bicep curl"),
    "Plank": ("plank", "unterarmstutz"),
    "Side Plank": ("seitstutz", "side plank"),
    "Dead Bug": ("dead bug",),
    "Box Jump": ("box jump", "box jumps"),
    "Kettlebell Swing": ("kettlebell swing",),
}


class GarminStrengthMappingError(ValueError):
    """A structure that cannot become a Garmin strength workout."""


@dataclass(frozen=True)
class GarminExercise:
    """One catalogue entry: the display name and the pair a workout step needs."""

    name: str
    category: str
    exercise: str


def _fold(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.split())


_WORD: Final = re.compile(r"[a-z0-9]+")


def _words(text: Any) -> tuple[str, ...]:
    """Folded words without hyphens or a plural s: ``Lat-Pulldowns`` -> lat, pulldown."""
    return tuple(
        word[:-1] if len(word) > 3 and word.endswith("s") else word
        for word in _WORD.findall(_fold(text))
    )


def _key(text: Any) -> str:
    """Spacing- and hyphen-free key, so ``Lat-Pulldown`` meets ``lat pull-down``."""
    return "".join(_words(text))


_ALIASES: Final = {
    _key(alias): name for name, aliases in _ALIAS_GROUPS.items() for alias in aliases
}


def catalogue_available() -> bool:
    return _catalogue is not None


def _by_folded_name() -> dict[str, GarminExercise]:
    if _catalogue is None:
        return {}
    return {
        _fold(item["name"]): GarminExercise(
            item["name"], item["category"], item["exercise"]
        )
        for item in _catalogue.EXERCISES
    }


_INDEX: Final = _by_folded_name()


def _by_key() -> dict[str, GarminExercise]:
    index: dict[str, GarminExercise] = {}
    for entry in _INDEX.values():
        # The first catalogue entry wins a key collision; exact names win first.
        index.setdefault(_key(entry.name), entry)
    return index


_KEY_INDEX: Final = _by_key()


def catalogue_exercise(name: Any) -> GarminExercise | None:
    """Return the catalogue entry whose display name matches ``name``."""
    return _INDEX.get(_fold(name))


def _loose_match(name: Any) -> GarminExercise | None:
    """Match ignoring spacing, hyphens and a plural s, then an alias, then words.

    The word fallback takes the catalogue entry that contains every word of
    ``name`` with the fewest extra words, only when exactly one entry has that
    count, so ``Pull Face`` finds ``Face Pull`` while ``Row`` stays unresolved.
    """
    key = _key(name)
    if not key:
        return None
    if (exact := _KEY_INDEX.get(key)) is not None:
        return exact
    if (alias := _ALIASES.get(key)) is not None:
        return catalogue_exercise(alias)
    words = set(_words(name))
    candidates = [
        (len(entry_words), entry)
        for entry in _INDEX.values()
        if words <= (entry_words := set(_words(entry.name)))
    ]
    if not candidates:
        return None
    fewest = min(size for size, _entry in candidates)
    best = [entry for size, entry in candidates if size == fewest]
    return best[0] if len(best) == 1 else None


_IDENTIFIER: Final = re.compile(r"[A-Z0-9_]{1,64}")


def stored_pair(item: Mapping[str, Any]) -> GarminExercise | None:
    """Return a well-formed stored ``garmin_pair`` with its catalogue name."""
    pair = item.get("garmin_pair")
    name = str(item.get("garmin_exercise") or "").strip()
    if not isinstance(pair, Mapping) or not name:
        return None
    category, exercise = (str(pair.get(key) or "") for key in ("category", "exercise"))
    if not (_IDENTIFIER.fullmatch(category) and _IDENTIFIER.fullmatch(exercise)):
        return None
    return GarminExercise(name[:_NAME_LIMIT], category, exercise)


def resolve_exercise(item: Mapping[str, Any]) -> GarminExercise | None:
    """Resolve one exercise: catalogue field, stored pair, its name, then loosely.

    The stored pair keeps a resolution valid when a later catalogue renames
    the exercise; Garmin's read-back check still catches a pair it dropped.
    """
    if (explicit := catalogue_exercise(item.get("garmin_exercise"))) is not None:
        return explicit
    if (stored := stored_pair(item)) is not None:
        return stored
    if (by_name := catalogue_exercise(item.get("name"))) is not None:
        return by_name
    return _loose_match(item.get("name"))


def suggestions(text: Any) -> list[str]:
    """Up to five catalogue names sharing the longest word of ``text``."""
    words = sorted(
        (word for word in re.findall(r"[a-z0-9-]+", _fold(text)) if len(word) > 2),
        key=len,
        reverse=True,
    )
    found: list[str] = []
    for word in words:
        for folded, entry in _INDEX.items():
            if word in folded and entry.name not in found:
                found.append(entry.name)
                if len(found) == MAX_SUGGESTIONS:
                    return found
    return found


def _plain(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else f"{value:g}"


def _relative_load_note(item: Mapping[str, Any]) -> str | None:
    if item.get("pct_1rm") is not None:
        return f"{_plain(item['pct_1rm'])} % 1RM"
    if item.get("rpe") is not None:
        return f"RPE {_plain(item['rpe'])}"
    if item.get("rir") is not None:
        return f"{item['rir']} RIR"
    return None


def _step_note(item: Mapping[str, Any]) -> str | None:
    parts = (_relative_load_note(item), str(item.get("note") or "").strip())
    return " · ".join(part for part in parts if part)[:_NOTE_LIMIT] or None


def _exercise_step(
    order: int,
    item: Mapping[str, Any],
    exercise: GarminExercise,
    step_type: Mapping[str, Any],
    note: str | None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(step_type),
        "endCondition": dict(_REPS_END),
        "endConditionValue": float(item["reps"]),
        "targetType": dict(_NO_TARGET),
        "category": exercise.category,
        "exerciseName": exercise.exercise,
    }
    if item.get("kg") is not None and float(item["kg"]) > 0:
        step["weightValue"] = float(item["kg"]) * 1000.0
        step["weightUnit"] = dict(_WEIGHT_UNIT)
    if note:
        step["description"] = note
    return step


def _rest_step(order: int, seconds: int) -> dict[str, Any]:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_REST_STEP),
        "endCondition": dict(_TIME_END),
        "endConditionValue": float(seconds),
        "targetType": dict(_NO_TARGET),
    }


def _set_group(
    order: int,
    sets: Mapping[str, Any],
    exercise: GarminExercise,
    rest_s: int,
    step_type: Mapping[str, Any],
    note: str | None = None,
) -> tuple[dict[str, Any], int]:
    """One repeat group of ``sets`` (sets, reps, kg) and its rest; next order."""
    inner = [_exercise_step(order + 1, sets, exercise, step_type, note)]
    if rest_s:
        inner.append(_rest_step(order + 2, rest_s))
    group = {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": dict(_REPEAT_STEP),
        "numberOfIterations": int(sets["sets"]),
        "workoutSteps": inner,
        "endCondition": dict(_ITERATIONS_END),
        "endConditionValue": float(sets["sets"]),
        "smartRepeat": False,
    }
    return group, order + 1 + len(inner)


def resolved_exercises(
    exercises: Sequence[Mapping[str, Any]],
) -> list[GarminExercise]:
    """Resolve every exercise or raise naming each unresolved one with suggestions."""
    if not catalogue_available():
        raise GarminStrengthMappingError(
            "Der Garmin-Übungskatalog ist auf diesem Server nicht verfügbar."
        )
    resolved: list[GarminExercise] = []
    missing: list[str] = []
    for item in exercises:
        found = resolve_exercise(item)
        if found is None:
            hint = suggestions(item.get("garmin_exercise") or item.get("name"))
            label = str(item.get("name") or "?")
            missing.append(
                f"{label} (Vorschläge: {', '.join(hint)})" if hint else label
            )
        else:
            resolved.append(found)
    if missing:
        raise GarminStrengthMappingError(
            "Keine Garmin-Übung zugeordnet: " + "; ".join(missing)
        )
    return resolved


def strength_workout(
    *, name: str, description: str, exercises: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Return the Garmin workout JSON for a validated, non-empty structure."""
    if not exercises:
        raise GarminStrengthMappingError(NO_STRUCTURE_MESSAGE)
    resolved = resolved_exercises(exercises)
    steps: list[dict[str, Any]] = []
    order = 1
    for item, exercise in zip(exercises, resolved, strict=True):
        rest_s = int(item.get("rest_s") or 0)
        warmup = item.get("warmup")
        if isinstance(warmup, Mapping) and warmup.get("sets"):
            # Warm-up sets are their own step before the working sets.
            group, order = _set_group(order, warmup, exercise, rest_s, _WARMUP_STEP)
            steps.append(group)
        group, order = _set_group(
            order, item, exercise, rest_s, _INTERVAL_STEP, _step_note(item)
        )
        steps.append(group)
    return {
        "workoutName": (str(name).strip() or "Krafteinheit")[:_NAME_LIMIT],
        "description": str(description or "")[:_DESCRIPTION_LIMIT],
        "sportType": dict(STRENGTH_SPORT),
        "estimatedDurationInSecs": 0,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": dict(STRENGTH_SPORT),
                "workoutSteps": steps,
            }
        ],
    }


_EXERCISE_STEP_KEYS: Final = frozenset({"interval", "warmup"})


def _exercise_steps(steps: Any) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, Mapping):
            continue
        kind = str((step.get("stepType") or {}).get("stepTypeKey") or "")
        if step.get("type") == "RepeatGroupDTO":
            pairs.extend(_exercise_steps(step.get("workoutSteps")))
        elif kind in _EXERCISE_STEP_KEYS:
            pairs.append(
                (
                    kind,
                    str(step.get("category") or ""),
                    str(step.get("exerciseName") or ""),
                )
            )
    return pairs


def workout_exercise_steps(workout: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Return (step type, category, exercise) of every exercise step, in order.

    The step type keeps a warm-up step that Garmin turned into a working set,
    or dropped, from passing the read-back check.
    """
    pairs: list[tuple[str, str, str]] = []
    for segment in workout.get("workoutSegments") or []:
        if isinstance(segment, Mapping):
            pairs.extend(_exercise_steps(segment.get("workoutSteps")))
    return pairs
