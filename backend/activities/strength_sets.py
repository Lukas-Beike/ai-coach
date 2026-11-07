"""Executed strength sets of a session: selection, summary and plan comparison.

One stored set list per session is used, never merged set by set: Garmin's
exercise sets (which carry the athlete's Connect corrections) first, then the
file set lists in a stable provider order. The summary groups the active sets of each
exercise over the whole session (supersets included), in order of first
appearance; the rest after a set is the duration of the rest set that follows
it. Exercise names are provider codes (upper-case identifiers), never free text.
Strength volume is reported on its own and never added to TSS or session-RPE
load.

Exercise categories decide leg strength: any leg category makes the session leg;
it is not leg only when every exercise has a known non-leg category. ``other``
(unrecognized) and the neutral ``cardio``, ``warm_up`` and ``run`` categories
decide nothing.

A planned ``strength_structure`` exercise is compared by exercise category: the
category of its Garmin catalogue exercise (explicit, stored pair, name or the
small alias list). A planned exercise without a known category is ``unknown``,
never a miss; so is one whose category was not recognized in a session that
has unrecognized sets. A planned exercise counts its sets done at or above the
planned reps; a set without reported reps counts as done, as nothing shows it
fell short.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any, Final

from backend.canonical.activity_detail import (
    ActivityStrengthSet,
    ActivityStrengthSetSet,
)
from backend.canonical.vocabulary import (
    ExerciseCategory,
    StrengthSetSource,
    StrengthSetType,
)
from backend.db.activity_detail_store import (
    StoredDetailSet,
    strength_sets_for_sessions,
)
from backend.providers import garmin_strength_workout

# Exercise categories that load the legs: lower-body strength, full body and
# plyometrics (the same rule as the legs, full_body and plyometrics focus).
LEG_CATEGORIES: Final = frozenset(
    {
        ExerciseCategory.SQUAT,
        ExerciseCategory.DEADLIFT,
        ExerciseCategory.LUNGE,
        ExerciseCategory.LEG_CURL,
        ExerciseCategory.CALF_RAISE,
        ExerciseCategory.HIP_RAISE,
        ExerciseCategory.HIP_SWING,
        ExerciseCategory.OLYMPIC_LIFT,
        ExerciseCategory.PLYO,
        ExerciseCategory.TOTAL_BODY,
    }
)
# Categories that say nothing about the body part trained.
NEUTRAL_CATEGORIES: Final = frozenset(
    {
        ExerciseCategory.OTHER,
        ExerciseCategory.CARDIO,
        ExerciseCategory.WARM_UP,
        ExerciseCategory.RUN,
    }
)
MAX_EXERCISES: Final = 20
STRENGTH_KEY: Final = "strength_sets"


def select_strength_sets(
    stored: Iterable[StoredDetailSet],
) -> StoredDetailSet | None:
    """The one strength set list a session uses, or None without any."""
    candidates = [
        item for item in stored if isinstance(item.detail, ActivityStrengthSetSet)
    ]
    return min(candidates, key=strength_rank, default=None)


def strength_rank(item: StoredDetailSet) -> tuple[Any, ...]:
    """Exercise sets (with the athlete's corrections) before file sets."""
    detail = _detail(item)
    return (
        detail.source is not StrengthSetSource.GARMIN_EXERCISE_SETS,
        item.provider,
        item.provider_activity_id,
    )


def _detail(item: StoredDetailSet) -> ActivityStrengthSetSet:
    detail = item.detail
    if not isinstance(detail, ActivityStrengthSetSet):
        raise TypeError("not a strength set list")
    return detail


def strength_summary(item: StoredDetailSet, *, set_list: bool) -> dict[str, Any]:
    """Bounded summary of one stored set list; ``set_list`` adds every set."""
    detail = _detail(item)
    exercises = _exercises(detail.sets)
    active = [s for s in detail.sets if s.set_type is StrengthSetType.ACTIVE]
    reps = [s.reps for s in active if s.reps is not None]
    volume = [s.reps * s.weight_kg for s in active if s.reps and s.weight_kg]
    by_category: dict[str, list[int | None]] = {}
    unrecognized = 0
    for item_set in active:
        category = item_set.exercise_category
        if category is None or category is ExerciseCategory.OTHER:
            unrecognized += 1
        else:
            by_category.setdefault(category.value, []).append(item_set.reps)
    summary: dict[str, Any] = {
        "source": detail.source.value,
        "provider": item.provider,
        "active_sets": len(active),
        "total_reps": sum(reps) if reps else None,
        "volume_kg": round(sum(volume), 1) if volume else None,
        "leg": _leg(group["category"] for group in exercises),
        # Reps per recognized category over every active set, for the plan
        # comparison; the exercise list below is bounded for display.
        "by_category": by_category,
        "unrecognized_sets": unrecognized,
        "exercises": [
            _exercise_entry(group, set_list=set_list)
            for group in exercises[:MAX_EXERCISES]
        ],
    }
    if len(exercises) > MAX_EXERCISES:
        summary["omitted_exercises"] = len(exercises) - MAX_EXERCISES
    return summary


def _exercises(sets: Sequence[ActivityStrengthSet]) -> list[dict[str, Any]]:
    """Active sets per exercise over the session; a rest set adds its duration."""
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    last_set: dict[str, Any] | None = None
    for item in sets:
        if item.set_type is StrengthSetType.REST:
            if last_set is not None and item.duration_s is not None:
                last_set["rest_s"] = round(item.duration_s)
            continue
        key = (item.exercise_category, item.exercise_name)
        group = groups.setdefault(
            key,
            {
                "category": item.exercise_category,
                "name": item.exercise_name,
                "sets": [],
            },
        )
        last_set = {
            "reps": item.reps,
            "weight_kg": item.weight_kg,
            "duration_s": None if item.duration_s is None else round(item.duration_s),
        }
        group["sets"].append(last_set)
    return list(groups.values())


def _exercise_entry(group: Mapping[str, Any], *, set_list: bool) -> dict[str, Any]:
    category: ExerciseCategory | None = group["category"]
    sets: list[dict[str, Any]] = group["sets"]
    loaded = [s for s in sets if s["weight_kg"] is not None]
    top = max(loaded, key=lambda s: s["weight_kg"]) if loaded else None
    entry: dict[str, Any] = {
        "category": None if category is None else category.value,
        "name": group["name"],
        "leg": _category_leg(category),
        "sets": len(sets),
        "top_kg": None if top is None else top["weight_kg"],
        "top_reps": None if top is None else top["reps"],
    }
    if set_list:
        entry["reps"] = [s["reps"] for s in sets]
        entry["set_list"] = sets
    return entry


def _category_leg(category: ExerciseCategory | None) -> bool | None:
    if category is None or category in NEUTRAL_CATEGORIES:
        return None
    return category in LEG_CATEGORIES


def _leg(categories: Iterable[ExerciseCategory | None]) -> bool | None:
    """True with any leg exercise, False when every exercise is known non-leg."""
    decided = [
        _category_leg(category)
        for category in categories
        if category not in NEUTRAL_CATEGORIES
    ]
    if any(decided):
        return True
    if decided and all(value is False for value in decided):
        return False
    return None


def strength_summaries(
    db: Any, activity_ids: Collection[str], *, set_list: bool = False
) -> dict[str, dict[str, Any]]:
    """Summary of the selected strength set list per session id."""
    return {
        activity_id: strength_summary(selected, set_list=set_list)
        for activity_id, selected in strength_sets_for_sessions(
            db, activity_ids, rank=strength_rank
        ).items()
    }


def with_strength_summaries(
    summaries: Iterable[Mapping[str, Any]], stored: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """Return the summaries with their executed strength sets, when stored."""
    result = []
    for summary in summaries:
        item = dict(summary)
        found = stored.get(str(item.get("id")))
        if found is not None:
            item[STRENGTH_KEY] = dict(found)
        result.append(item)
    return tuple(result)


def planned_category(exercise: Mapping[str, Any]) -> ExerciseCategory | None:
    """Category of one planned exercise through the Garmin catalogue, else None."""
    resolved = garmin_strength_workout.resolve_exercise(exercise)
    if resolved is None:
        return None
    try:
        return ExerciseCategory(resolved.category.lower())
    except ValueError:
        return ExerciseCategory.OTHER


def plan_comparison(
    structure: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Planned against executed sets per exercise, or None without a usable side.

    Executed sets of one category go to the planned exercises of that category
    in plan order. ``percentage`` is the share of planned sets of the matched
    exercises done at or above the planned reps; None when nothing matched.
    """
    by_category = summary.get("by_category")
    if not structure or not isinstance(by_category, Mapping) or not by_category:
        return None
    pools = {key: list(value) for key, value in by_category.items()}
    unrecognized = bool(summary.get("unrecognized_sets"))
    rows: list[dict[str, Any]] = []
    planned_total = done_total = 0
    for item in structure:
        rows.append(row := _planned_row(item, pools, unrecognized=unrecognized))
        if row["status"] == "matched":
            planned_total += row["planned_sets"]
            done_total += row["completed_sets"]
    return {
        "basis": "strength_sets",
        "planned_sets": planned_total,
        "completed_sets": done_total,
        "percentage": round(done_total * 100 / planned_total)
        if planned_total
        else None,
        "exercises": rows,
    }


def _planned_row(
    item: Mapping[str, Any],
    pools: dict[str, list[int | None]],
    *,
    unrecognized: bool,
) -> dict[str, Any]:
    category = planned_category(item)
    planned_sets = int(item.get("sets") or 0)
    planned_reps = int(item.get("reps") or 0)
    row: dict[str, Any] = {
        "name": item.get("name"),
        "category": None if category is None else category.value,
        "planned_sets": planned_sets,
        "planned_reps": planned_reps,
        "planned_kg": item.get("kg"),
    }
    pool = [] if category is None else pools.get(category.value, [])
    if (
        category is None
        or category is ExerciseCategory.OTHER
        or (not pool and unrecognized)
    ):
        return {**row, "status": "unknown"}
    # Garmin records the planned warm-up sets first, as ordinary sets of the
    # same category; they are not working sets. Only sets beyond the planned
    # working sets count as warm-ups, so a skipped warm-up costs no working set.
    warmup = item.get("warmup")
    warmup_sets = int(warmup.get("sets") or 0) if isinstance(warmup, Mapping) else 0
    skip = min(warmup_sets, max(0, len(pool) - planned_sets))
    pool = pool[skip:]
    taken, pools[category.value] = pool[:planned_sets], pool[planned_sets:]
    completed = sum(1 for reps in taken if reps is None or reps >= planned_reps)
    return {
        **row,
        "status": "matched",
        "done_sets": len(taken),
        "completed_sets": completed,
        "reps": taken,
    }
