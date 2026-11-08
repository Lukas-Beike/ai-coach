"""Session focus ("Art der Einheit") of a planned unit or library template.

The athlete or the Coach sets ``session_focus`` (and for strength
``strength_intensity``) in the unit payload. A unit without it gets a *derived*
focus, first from its parsed workout steps, then from keywords in its text;
otherwise it is unknown. A derived focus is never presented as set. No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from backend.activities.workout_load import WorkoutEstimate
from backend.canonical import planning_fields
from backend.canonical.planning_fields import (
    SESSION_FOCUS,
    SESSION_FOCUS_KEYS,
    STRENGTH_INTENSITY,
    STRENGTH_STRUCTURE,
)
from backend.canonical.vocabulary import Sport
from backend.errors import AppError
from backend.planning import strength_structure
from backend.planning.sport import planned_sport_environment

FOCUS_KEY: Final = SESSION_FOCUS
INTENSITY_KEY: Final = STRENGTH_INTENSITY
FOCUS_KEYS: Final = SESSION_FOCUS_KEYS

ENDURANCE_FOCI: Final = planning_fields.ENDURANCE_FOCI
RIDE_FOCI: Final = planning_fields.RIDE_FOCI
STRENGTH_FOCI: Final = planning_fields.STRENGTH_FOCI
STRENGTH_INTENSITIES: Final = ("light", "moderate", "heavy")
ALL_FOCI: Final = (*RIDE_FOCI, *STRENGTH_FOCI)
# Hard endurance sessions; a set focus decides hardness before any text rule.
HARD_FOCI: Final = frozenset(
    {"threshold", "sweet_spot", "vo2max", "anaerobic", "race", "test"}
)
LEG_FOCI: Final = frozenset({"legs", "full_body", "plyometrics"})

Origin = Literal["set", "derived"]
_LONG_SESSION_S = 5400
_TEMPO_STEP_S = 1200
_HARD_STEP_S = 300
_EASY_INTENSITY = 0.75


@dataclass(frozen=True)
class SessionFocus:
    """Focus of a unit; ``origin`` is ``None`` when it is unknown."""

    value: str | None = None
    strength_intensity: str | None = None
    origin: Origin | None = None
    intensity_origin: Origin | None = None

    @property
    def is_hard(self) -> bool | None:
        """Whether the focus is a hard endurance session; ``None`` if unknown."""
        return None if self.value is None else self.value in HARD_FOCI

    @property
    def is_leg_strength(self) -> bool:
        """Legs, full body or plyometrics strength (for the leg-strength checks)."""
        return self.value in LEG_FOCI

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_focus": self.value,
            "strength_intensity": self.strength_intensity,
            "focus_origin": self.origin,
            "intensity_origin": self.intensity_origin,
        }


def allowed_foci(sport: Sport) -> tuple[str, ...]:
    if sport is Sport.STRENGTH:
        return STRENGTH_FOCI
    if sport is Sport.RIDE:
        return RIDE_FOCI
    return ENDURANCE_FOCI if sport is Sport.RUN else ()


def _invalid(message: str) -> AppError:
    return AppError(400, message, reason="invalid_session_focus")


def _text_value(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    text = str(value).strip().casefold() if value is not None else ""
    return text or None


def _set_structure(record: dict[str, Any], sport: Sport, value: Any) -> None:
    exercises = strength_structure.normalize_structure(value)
    if exercises is None:
        return
    if sport is not Sport.STRENGTH:
        raise _invalid("Die Kraftstruktur gibt es nur für Krafteinheiten.")
    record[STRENGTH_STRUCTURE] = exercises
    record["description"] = strength_structure.render(exercises)


def normalize_session_focus(record: dict[str, Any]) -> None:
    """Validate the focus fields of a unit in place; empty values are removed.

    The focus must exist for the unit's sport; strength intensity and the
    strength structure only on strength. A structure replaces the description
    with the text generated from it.
    """
    sport = planned_sport_environment(record)[0]
    focus = _text_value(record, FOCUS_KEY)
    intensity = _text_value(record, INTENSITY_KEY)
    structure = record.get(STRENGTH_STRUCTURE)
    for key in FOCUS_KEYS:
        record.pop(key, None)
    if focus is not None:
        if focus not in allowed_foci(sport):
            raise _invalid("Ungültige Art der Einheit für diese Sportart.")
        record[FOCUS_KEY] = focus
    if intensity is not None:
        if sport is not Sport.STRENGTH or intensity not in STRENGTH_INTENSITIES:
            raise _invalid("Ungültige Krafteinheit-Intensität.")
        record[INTENSITY_KEY] = intensity
    _set_structure(record, sport, structure)


# Strength keywords; the first matching group wins, legs plus upper is full body.
_LEGS = "squat|kniebeuge|dead ?lift|kreuzheben|lunge|ausfallschritt|leg press"
_LEGS_MORE = "beinpresse|step[ -]?up|calf raise|wadenheben|hip thrust|lower body"
_LEGS_DAY = r"leg day|beintag|\bbeine?\b|\blegs?\b|unterk(?:ö|o|oe)rper"
_UPPER = "bench|bankdr(?:ü|u|ue)cken|pull[ -]?ups?|klimmz(?:u|ü|ue)?g|rudern"
_UPPER_MORE = (
    r"\brows?\b|overhead press|schulterdr(?:ü|u|ue)cken|upper body|oberk(?:ö|o|oe)rper"
)
_STRENGTH_PATTERNS: Final = (
    ("plyometrics", "plyo|spr(?:ü|u|ue)nge|box[ -]?jump|jump squat|sprungkraft"),
    ("legs", f"{_LEGS}|{_LEGS_MORE}|{_LEGS_DAY}"),
    ("upper", f"{_UPPER}|{_UPPER_MORE}"),
    ("core", r"\bcore\b|rumpf|plank"),
    ("mobility", "mobility|mobilit(?:ä|a|ae)t|dehn|stretch"),
)
_ENDURANCE_PATTERNS: Final = (
    ("recovery", r"regeneration|recovery|\bregen\b"),
    ("threshold", r"schwelle|threshold"),
    ("vo2max", r"vo2|intervalle|\bintervals\b(?!\.icu)"),
    ("tempo", r"\btempo"),
    ("long", r"\blang(?:e[rnsm]?)?\b|\blong"),
    ("endurance", r"grundlage|endurance|\bbase\b"),
    ("easy", r"locker|\beasy\b"),
)
_COMPILED = {
    group: tuple((focus, re.compile(pattern, re.IGNORECASE)) for focus, pattern in rows)
    for group, rows in (
        ("strength", _STRENGTH_PATTERNS),
        ("endurance", _ENDURANCE_PATTERNS),
    )
}


def _structure(unit: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The stored exercises of a unit; an invalid stored value counts as none."""
    value = unit.get(STRENGTH_STRUCTURE)
    return (
        [i for i in value if isinstance(i, Mapping)] if isinstance(value, list) else []
    )


_WORD_RUN = r"[\w-]+"
# A negated mention names what the session spares, not what it trains:
# "Beine schonen", "ohne Beine", "kein Beintraining", "nicht schwer", "no legs".
_NEGATED: Final = re.compile(
    rf"\b(?:ohne|keine?[nmrs]?|nicht|no|without|not)\s+{_WORD_RUN}"
    rf"|{_WORD_RUN}\s+(?:schonen|entlasten|auslassen|weglassen|pausieren)\b",
    re.IGNORECASE,
)
# An explicit focus term in the unit name wins over exercise keywords.
_NAME_FOCUS: Final = tuple(
    (focus, re.compile(pattern, re.IGNORECASE))
    for focus, pattern in (
        ("full_body", r"ganzk(?:ö|o|oe)rper|full[ -]?body"),
        ("upper", r"oberk(?:ö|o|oe)rper|upper[ -]?body"),
        ("legs", r"unterk(?:ö|o|oe)rper|lower[ -]?body|\bbeine?\b|beintag|leg day"),
        ("core", r"\bcore\b|rumpf"),
        ("mobility", r"mobility|mobilit(?:ä|a|ae)t"),
    )
)
_TEXT_INTENSITY: Final = tuple(
    (intensity, re.compile(pattern, re.IGNORECASE))
    for intensity, pattern in (
        ("heavy", r"\b(?:heavy|schwer|[1-6]\s*rm)\b"),
        ("moderate", r"\b(?:moderate|moderat|mittel(?:schwer)?)\b"),
        ("light", r"\b(?:light|leicht)\b"),
    )
)


def _affirmed(text: Any) -> str:
    """Text without negated mentions."""
    return _NEGATED.sub(" ", str(text or ""))


def _name_focus(unit: Mapping[str, Any]) -> str | None:
    """The one focus the name names explicitly, else ``None``."""
    name = _affirmed(unit.get("name"))
    found = [focus for focus, rx in _NAME_FOCUS if rx.search(name)]
    return found[0] if len(found) == 1 else None


def _keyword_candidates(unit: Mapping[str, Any], sport: Sport) -> list[str]:
    """Every focus the text names, best match first (several mean it is ambiguous)."""
    text = _affirmed(f"{unit.get('name') or ''} {unit.get('description') or ''}")
    if sport is Sport.STRENGTH:
        if (named := _name_focus(unit)) is not None:
            return [named]
        found = [f for f, rx in _COMPILED["strength"] if rx.search(text)]
        if "legs" in found and "upper" in found:
            return ["full_body", *(f for f in found if f not in {"legs", "upper"})]
        return found
    return [f for f, rx in _COMPILED["endurance"] if rx.search(text)]


def _keyword_focus(unit: Mapping[str, Any], sport: Sport) -> str | None:
    candidates = _keyword_candidates(unit, sport)
    return candidates[0] if candidates else None


def structure_intensity(unit: Mapping[str, Any]) -> str | None:
    """Hardest relative load of the unit's stored structure, else ``None``."""
    return strength_structure.derived_intensity(_structure(unit))


def _text_intensities(unit: Mapping[str, Any]) -> list[str]:
    """Every intensity the name or description names, the hardest first."""
    text = _affirmed(f"{unit.get('name') or ''} {unit.get('description') or ''}")
    return [value for value, rx in _TEXT_INTENSITY if rx.search(text)]


def text_intensity(unit: Mapping[str, Any]) -> str | None:
    """Intensity a strength unit's name or description names, the hardest first.

    Negated mentions do not count.
    """
    return next(iter(_text_intensities(unit)), None)


def _step_focus(estimate: WorkoutEstimate | None) -> str | None:
    """Focus from parsed steps and computed intensity; ``None`` if unresolved."""
    if estimate is None or not estimate.steps or estimate.intensity_factor is None:
        return None
    seconds: dict[int, float] = {}
    for step in estimate.steps:
        seconds[step.zone or 0] = seconds.get(step.zone or 0, 0.0) + (
            step.duration_s or 0.0
        )
    high = max(
        (z for z, s in seconds.items() if z >= 4 and s >= _HARD_STEP_S), default=0
    )
    if high:
        return {4: "threshold", 5: "vo2max"}.get(high, "anaerobic")
    if seconds.get(3, 0.0) >= _TEMPO_STEP_S:
        return "tempo"
    if (estimate.duration_s or 0.0) >= _LONG_SESSION_S:
        return "long"
    return "easy" if estimate.intensity_factor < _EASY_INTENSITY else None


def _intensity(
    unit: Mapping[str, Any], sport: Sport
) -> tuple[str | None, Origin | None]:
    """Set strength intensity, else derived from the structure, else the text."""
    if sport is not Sport.STRENGTH:
        return None, None
    intensity = _text_value(unit, INTENSITY_KEY)
    if intensity in STRENGTH_INTENSITIES:
        return intensity, "set"
    derived = structure_intensity(unit) or text_intensity(unit)
    return derived, None if derived is None else "derived"


def session_focus(
    unit: Mapping[str, Any], estimate: WorkoutEstimate | None = None
) -> SessionFocus:
    """Set focus first, then the step-derived, then the keyword-derived focus.

    For strength an explicit focus term in the name beats exercise keywords,
    and negated mentions ("Beine schonen") never count. The strength intensity
    is the set one, else derived from the structure, else from the text.
    """
    sport = planned_sport_environment(unit)[0]
    allowed = allowed_foci(sport)
    value = _text_value(unit, FOCUS_KEY)
    intensity, intensity_origin = _intensity(unit, sport)
    if value in allowed:
        return SessionFocus(value, intensity, "set", intensity_origin)
    if not allowed:
        return SessionFocus()
    derived = (
        None if sport is Sport.STRENGTH else _step_focus(estimate)
    ) or _keyword_focus(unit, sport)
    if derived is None or derived not in allowed:
        return SessionFocus(
            strength_intensity=intensity, intensity_origin=intensity_origin
        )
    return SessionFocus(derived, intensity, "derived", intensity_origin)


def _matches_description(target: Mapping[str, Any], carried: Mapping[str, Any]) -> bool:
    try:
        exercises = strength_structure.normalize_structure(carried[STRENGTH_STRUCTURE])
    except AppError:
        return False
    text = strength_structure.render(exercises or [])
    return text.split() == str(target.get("description") or "").split()


def carry_focus(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Keep the local focus on a remote payload when it fits the payload's sport.

    The structure stays only while the remote description still equals its text;
    a description edited remotely wins as free text.
    """
    carried = {key: source[key] for key in FOCUS_KEYS if source.get(key) is not None}
    if STRENGTH_STRUCTURE in carried:
        carried[STRENGTH_STRUCTURE] = strength_structure.without_unknown_garmin(
            carried[STRENGTH_STRUCTURE]
        )
    if STRENGTH_STRUCTURE in carried and not _matches_description(target, carried):
        del carried[STRENGTH_STRUCTURE]
    candidate = {**target, **carried}
    try:
        normalize_session_focus(candidate)
    except AppError:
        return
    target.update({key: candidate[key] for key in FOCUS_KEYS if key in candidate})


def _unambiguous_focus(
    unit: Mapping[str, Any], estimate: WorkoutEstimate | None
) -> str | None:
    """The derived focus when its sources agree, else ``None``.

    A focus from the parsed steps stands unless the text names only other foci;
    without steps the text must name exactly one focus.
    """
    sport = planned_sport_environment(unit)[0]
    candidates = _keyword_candidates(unit, sport)
    stepped = None if sport is Sport.STRENGTH else _step_focus(estimate)
    if stepped is not None:
        return stepped if not candidates or stepped in candidates else None
    return candidates[0] if len(candidates) == 1 else None


def unambiguous_values(
    unit: Mapping[str, Any], estimate: WorkoutEstimate | None = None
) -> dict[str, str]:
    """Focus fields a unit lacks that can be derived without doubt.

    Only keys not yet stored are returned: the focus (sport with a focus
    vocabulary) and, for strength, the intensity (from the structure, else from
    exactly one named level). Anything contested stays a suggestion.
    """
    sport = planned_sport_environment(unit)[0]
    allowed = allowed_foci(sport)
    values: dict[str, str] = {}
    if allowed and _text_value(unit, FOCUS_KEY) not in allowed:
        focus = _unambiguous_focus(unit, estimate)
        if focus in allowed:
            values[FOCUS_KEY] = str(focus)
    if sport is Sport.STRENGTH and _text_value(unit, INTENSITY_KEY) not in (
        STRENGTH_INTENSITIES
    ):
        named = _text_intensities(unit)
        intensity = structure_intensity(unit) or (named[0] if len(named) == 1 else None)
        if intensity in STRENGTH_INTENSITIES:
            values[INTENSITY_KEY] = str(intensity)
    return values
