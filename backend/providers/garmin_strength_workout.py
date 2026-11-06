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
_NAME_LIMIT: Final = 80
_NOTE_LIMIT: Final = 100
_DESCRIPTION_LIMIT: Final = 1000
STRENGTH_SPORT: Final = {
    "sportTypeId": 5,
    "sportTypeKey": "strength_training",
    "displayOrder": 5,
}
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
    "Barbell Back Squat": ("kniebeuge", "kniebeugen", "back squat", "squat"),
    "Barbell Front Squat": ("frontkniebeuge", "front squat"),
    "Goblet Squat": ("goblet squat",),
    "Barbell Deadlift": ("kreuzheben", "deadlift"),
    "Romanian Deadlift": ("rumanisches kreuzheben", "rdl"),
    "Barbell Bench Press": ("bankdrucken", "bench press"),
    "Alternating Dumbbell Lunge": (
        "ausfallschritt",
        "ausfallschritte",
        "lunge",
        "lunges",
    ),
    "Dumbbell Bulgarian Split Squat": (
        "bulgarian split squat",
        "bulgarische kniebeuge",
    ),
    "Dumbbell Step-up": ("step-up", "step-ups"),
    "Calf Raise": ("wadenheben", "calf raise"),
    "Leg Press": ("beinpresse", "leg press"),
    "Leg Curl": ("beinbeuger", "leg curl"),
    "Barbell Hip Thrust with Bench": ("hip thrust",),
    "Pull-up": ("klimmzuge", "klimmzug", "pull-up", "pull-ups"),
    "Push-up": ("liegestutze", "liegestutz", "push-up", "push-ups"),
    "Bent-over Row with Barbell": ("rudern", "langhantelrudern", "bent-over row"),
    "Barbell Shoulder Press": ("schulterdrucken",),
    "Barbell Overhead Press": ("overhead press",),
    "Lat Pull-down": ("latziehen", "lat pulldown"),
    "Plank": ("plank", "unterarmstutz"),
    "Side Plank": ("seitstutz", "side plank"),
    "Dead Bug": ("dead bug",),
    "Box Jump": ("box jump", "box jumps"),
    "Kettlebell Swing": ("kettlebell swing",),
}
_ALIASES: Final = {
    alias: name for name, aliases in _ALIAS_GROUPS.items() for alias in aliases
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


def catalogue_exercise(name: Any) -> GarminExercise | None:
    """Return the catalogue entry whose display name matches ``name``."""
    return _INDEX.get(_fold(name))


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
    """Resolve one exercise: catalogue field, stored pair, its name, then an alias.

    The stored pair keeps a resolution valid when a later catalogue renames
    the exercise; Garmin's read-back check still catches a pair it dropped.
    """
    if (explicit := catalogue_exercise(item.get("garmin_exercise"))) is not None:
        return explicit
    if (stored := stored_pair(item)) is not None:
        return stored
    if (by_name := catalogue_exercise(item.get("name"))) is not None:
        return by_name
    alias = _ALIASES.get(_fold(item.get("name")))
    return catalogue_exercise(alias) if alias else None


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


def _exercise_step(
    order: int, item: Mapping[str, Any], exercise: GarminExercise
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_INTERVAL_STEP),
        "endCondition": dict(_REPS_END),
        "endConditionValue": float(item["reps"]),
        "targetType": dict(_NO_TARGET),
        "category": exercise.category,
        "exerciseName": exercise.exercise,
    }
    if item.get("kg") is not None and float(item["kg"]) > 0:
        step["weightValue"] = float(item["kg"]) * 1000.0
        step["weightUnit"] = dict(_WEIGHT_UNIT)
    note = _relative_load_note(item)
    if note:
        step["description"] = note[:_NOTE_LIMIT]
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
        raise GarminStrengthMappingError("Die Einheit hat keine Kraftstruktur.")
    resolved = resolved_exercises(exercises)
    steps: list[dict[str, Any]] = []
    order = 1
    for item, exercise in zip(exercises, resolved, strict=True):
        inner = [_exercise_step(order + 1, item, exercise)]
        if item.get("rest_s"):
            inner.append(_rest_step(order + 2, int(item["rest_s"])))
        steps.append(
            {
                "type": "RepeatGroupDTO",
                "stepOrder": order,
                "stepType": dict(_REPEAT_STEP),
                "numberOfIterations": int(item["sets"]),
                "workoutSteps": inner,
                "endCondition": dict(_ITERATIONS_END),
                "endConditionValue": float(item["sets"]),
                "smartRepeat": False,
            }
        )
        order += 1 + len(inner)
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


def _exercise_pairs(steps: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, Mapping):
            continue
        if step.get("type") == "RepeatGroupDTO":
            pairs.extend(_exercise_pairs(step.get("workoutSteps")))
        elif (step.get("stepType") or {}).get("stepTypeKey") == "interval":
            pairs.append(
                (str(step.get("category") or ""), str(step.get("exerciseName") or ""))
            )
    return pairs


def workout_exercise_pairs(workout: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the (category, exercise) pair of every exercise step, in order."""
    pairs: list[tuple[str, str]] = []
    for segment in workout.get("workoutSegments") or []:
        if isinstance(segment, Mapping):
            pairs.extend(_exercise_pairs(segment.get("workoutSteps")))
    return pairs
