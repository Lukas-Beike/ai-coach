"""Input matrix for the Intervals workout export parity proof.

Inputs only. Expected outputs are recorded as sha256 digests from the
pre-change planning code in tests/fixtures/workout_export_parity.json.
"""

from __future__ import annotations

from typing import Any

TODAY_ISO = "2026-10-12"
ABSENT = "<absent>"
SPORT_VALUES: tuple[str, ...] = (
    "",
    " ride ",
    "AlpineSki",
    "BackcountrySki",
    "Badminton",
    "bicycle",
    "bike",
    "bike workout",
    "biking",
    "bogus",
    "Canoeing",
    "Crossfit",
    "cycling",
    "cycling workout",
    "E-Bike Ride",
    "e_mountain_bike_ride",
    "EBikeRide",
    "Elliptical",
    "EMountainBikeRide",
    "Golf",
    "gravel ride",
    "GravelRide",
    "gym",
    "Handcycle",
    "HighIntensityIntervalTraining",
    "Hike",
    "hiking",
    "IceSkate",
    "indoor cycling",
    "InlineSkate",
    "jog",
    "jogging",
    "Kayaking",
    "Kitesurf",
    "kraft",
    "krafttraining",
    "lauf",
    "laufen",
    "Mountain Bike",
    "MountainBikeRide",
    "NordicSki",
    "OpenWaterSwim",
    "Other",
    "other",
    "Padel",
    "Pickleball",
    "Pilates",
    "Racquetball",
    "rad",
    "rad indoor",
    "rad outdoor",
    "radfahren",
    "Ride",
    "ride",
    "ride\t",
    "road",
    "RockClimbing",
    "RollerSki",
    "row",
    "Rowing",
    "rowing",
    "Rugby",
    "RUN",
    "Run",
    "run",
    "run workout",
    "running",
    "Sail",
    "schwimmen",
    "Skateboard",
    "Snowboard",
    "Snowshoe",
    "Soccer",
    "Squash",
    "StairStepper",
    "Stand Up Paddling",
    "StandUpPaddling",
    "strength",
    "Surfing",
    "Swim",
    "swim",
    "swimming",
    "TableTennis",
    "Tennis",
    "trail run",
    "TrailRun",
    "Transition",
    "Velomobile",
    "virtual cycling",
    "virtual ride",
    "Virtual Row",
    "virtual_ride",
    "VirtualRide",
    "virtualride",
    "VirtualRow",
    "VirtualRun",
    "Walk",
    "walking",
    "WaterSport",
    "weight training",
    "weight-training",
    "Weight_Training",
    "weights",
    "WeightTraining",
    "weighttraining",
    "Wheelchair",
    "Windsurf",
    "Workout",
    "workout",
    "Yoga",
    "yoga",
    "Yoga ",
)
SPORT_REP: tuple[str, ...] = (
    "Ride",
    "VirtualRide",
    "Run",
    "WeightTraining",
    "Yoga",
    "Golf",
    "Canoeing",
    "Other",
    "Workout",
    "Rowing",
    "Swim",
    "bogus",
    "",
    "virtual ride",
    "Gym",
    "TrailRun",
    "Hike",
    "Walk",
)
NON_STRING_SPORTS: tuple[Any, ...] = (0, 1.5, True, ["Run"])
DESCRIPTIONS: tuple[str | None, ...] = (
    None,
    "",
    "Free text only",
    "- 60m Z2 HR",
    "- 1h30m Z2 HR\n- 10m Z4 HR",
    "- 6km Z1 HR\n- 4km Z2 HR",
    "- 100m /100m Pace",
    "- 2x 5m Z4 HR\n- 5m Z1 HR",
    "- 5m Z2\n\nNotes without a dash",
    "- 8 Z1 HR",
    "- 30m Z3 HR\n- 5m",
    "  - 45m z2 hr  ",
    "- 6km Z1 HR - 3km Z2 HR",
    "x" * 12005,
)
TARGETS: tuple[Any, ...] = (ABSENT, None, "AUTO", "POWER", "HR", "bogus")
DATES: tuple[Any, ...] = (
    TODAY_ISO,
    "2026-10-11",
    "2026-10-10",
    "2026-10-13",
    "2026-13-01",
    "2026-10-1",
    "",
    None,
    "2026-10-12T10:00:00",
    "not-a-date",
    ABSENT,
)
DURATIONS: tuple[Any, ...] = (ABSENT, None, 0, 4, 5, 60, 90, 600, 601, "45", "x", 45.7)
# Start values whose parsing depends on rewriting a trailing "Z" to "+00:00".
ZONED_STARTS: tuple[str, ...] = (
    "2026-10-12T07:30:00Z",
    "2026-10-12T07:30:00z",
    "2026-10-12t07:30:00Z",
    "2026-10-12T07:30:00.5Z",
    "2026-10-12T07:30Z",
    "2026-10-12T07:30:00+01:00Z",
    "2026-10-12T07:30:00ZZ",
    "2026-10-12T07:30:00Z+00:00",
    "2026-10-12Z",
)
STARTS: tuple[Any, ...] = (
    ABSENT,
    None,
    "",
    "2026-10-12T07:30:00",
    "2026-10-12T07:30:00Z",
    "2026-10-12",
    "2026-10-12T07:30:00" + "0" * 40,
    " 2026-10-12T07:30:00 ",
)
NAMES: tuple[Any, ...] = (ABSENT, None, "", "Long ride", "n" * 250)
MOVING: tuple[Any, ...] = (ABSENT, None, 3600, 1800.4, "bogus")
WORKOUT_IDS: tuple[str, ...] = ("local-1", "", "x" * 100, "library-a/b")
BASE: dict[str, Any] = {
    "date": TODAY_ISO,
    "sport": "Ride",
    "name": "Base ride",
    "description": "- 60m Z2 HR",
    "duration_minutes": 60,
    "target": "AUTO",
}


def with_fields(**fields: Any) -> dict[str, Any]:
    workout = dict(BASE)
    for key, value in fields.items():
        if isinstance(value, str) and value == ABSENT:
            workout.pop(key, None)
        else:
            workout[key] = value
    return workout


def payload_cases() -> list[tuple[str, str, dict[str, Any]]]:
    """Return (case id, workout id, workout) for workout_event_payload."""
    cases: list[tuple[str, str, dict[str, Any]]] = []

    def add(case_id: str, workout: dict[str, Any], workout_id: str = "local-1") -> None:
        cases.append((case_id, workout_id, workout))

    for sport in (*SPORT_VALUES, *NON_STRING_SPORTS):
        add(f"sport:{sport!r}", with_fields(sport=sport))
    for sport in SPORT_VALUES:
        add(f"type:{sport!r}", with_fields(sport=ABSENT, type=sport))
    add("sport-and-type-absent", with_fields(sport=ABSENT))
    for d_index, description in enumerate(DESCRIPTIONS):
        for sport in SPORT_REP:
            for target in TARGETS:
                add(
                    f"description:{d_index}:{sport!r}:{target!r}",
                    with_fields(sport=sport, description=description, target=target),
                )
    for date_value in DATES:
        for duration in DURATIONS:
            add(
                f"date:{date_value!r}:duration:{duration!r}",
                with_fields(date=date_value, duration_minutes=duration),
            )
    for moving in MOVING:
        for duration in (ABSENT, 60):
            add(
                f"moving:{moving!r}:duration:{duration!r}",
                with_fields(moving_time=moving, duration_minutes=duration),
            )
    for start in STARTS:
        add(f"start:{start!r}", with_fields(start_date_local=start))
    for name in NAMES:
        add(f"name:{name!r}", with_fields(name=name))
    for workout_id in WORKOUT_IDS:
        add(f"workout-id:{workout_id!r}", with_fields(), workout_id=workout_id)
    add("workout-empty-object", {})
    return cases


def normalize_cases() -> list[tuple[str, Any]]:
    """Return (case id, draft) for normalize_workout."""
    cases: list[tuple[str, Any]] = []
    for d_index, description in enumerate(DESCRIPTIONS):
        for sport in SPORT_REP:
            cases.append(
                (
                    f"description:{d_index}:{sport!r}",
                    {
                        "date": TODAY_ISO,
                        "sport": sport,
                        "name": "N",
                        "description": description,
                        "duration_minutes": 60,
                        "target": "AUTO",
                        "rationale": "r",
                    },
                )
            )
    for date_value in DATES:
        for duration in DURATIONS:
            for start in (*STARTS[:4], *ZONED_STARTS):
                draft = {
                    "date": date_value,
                    "sport": "Ride",
                    "description": "- 60m Z2 HR",
                    "duration_minutes": duration,
                    "rationale": "r",
                    "start_date_local": start,
                }
                cases.append(
                    (
                        f"date:{date_value!r}:duration:{duration!r}:start:{start!r}",
                        draft,
                    )
                )
    for rationale in ("", ABSENT):
        cases.append((f"rationale:{rationale!r}", {**BASE, "rationale": rationale}))
    non_dict_values: tuple[Any, ...] = (None, "x", [])
    for raw in non_dict_values:
        cases.append((f"non-dict:{raw!r}", raw))
    return cases


def sport_cases() -> list[tuple[str, Any]]:
    """Return (case id, raw sport value) for intervals_workout_sport."""
    values: list[Any] = [*SPORT_VALUES, *NON_STRING_SPORTS, None]
    return [(f"sport:{value!r}", value) for value in values]
