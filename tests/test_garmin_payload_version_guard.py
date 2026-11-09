"""The Garmin strength document cannot change without a PAYLOAD_VERSION bump (#1903).

``PAYLOAD_VERSION`` enters the push fingerprint of a unit, so units sent in an
older document form show as changed and can be sent again. It is bumped by
hand. This guard pins a hash of a fixed set of documents built by the real
builder together with the version that produced them. Changing the document
without bumping the version fails here.

The exercises carry their stored ``garmin_pair``, so the documents do not depend
on the contents of the ``garminconnect`` catalogue. The builder only asks that
the catalogue is importable, which this test stands in for. Run this module to
print the current pin.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any, Final
from unittest import mock

from backend.planning import strength_structure
from backend.providers import garmin_strength_workout as mapping
from backend.sync.garmin_strength_push import WORKOUT_MARKER

# (PAYLOAD_VERSION, sha256 of the canonical JSON of every document below).
PINNED: Final = (
    2,
    "a4d6ffc116ed563e674f43fae09f777605b24199a41f936b7f80a92741cd1216",
)


def _exercise(name: str, category: str, exercise: str, **fields: Any) -> dict[str, Any]:
    """An exercise as ``normalize_structure`` stores it, with its Garmin pair."""
    return {
        "name": name,
        "garmin_exercise": f"Pinned {name}",
        "garmin_pair": {"category": category, "exercise": exercise},
        **fields,
    }


# Weights in kilograms (whole, fractional, bodyweight), warm-up sets, each form of
# relative load, a note, rest of every length, and a plain rest-free exercise.
UNITS: Final = {
    "upper body": (
        "Oberkörper",
        [
            _exercise(
                "Schrägbankdrücken",
                "BENCH_PRESS",
                "INCLINE_BARBELL_BENCH_PRESS",
                sets=3,
                reps=8,
                kg=40,
                rir=2,
                rest_s=90,
                warmup={"sets": 1, "reps": 12, "kg": 20},
                note="nicht bis zum Muskelversagen",
            ),
            _exercise("Dips", "TRICEPS_EXTENSION", "BODY_WEIGHT_DIP", sets=4, reps=10),
            _exercise(
                "Rudern",
                "ROW",
                "BARBELL_ROW",
                sets=3,
                reps=10,
                kg=62.5,
                rpe=7.5,
                rest_s=120,
            ),
        ],
    ),
    "legs": (
        "Beine",
        [
            _exercise(
                "Kniebeuge",
                "SQUAT",
                "BARBELL_BACK_SQUAT",
                sets=5,
                reps=3,
                kg=100,
                pct_1rm=85,
                rest_s=180,
                warmup={"sets": 2, "reps": 5, "kg": 60},
            ),
            _exercise(
                "Plank",
                "PLANK",
                "PLANK",
                sets=3,
                reps=1,
                kg=0,
                rest_s=30,
                note="Zeit halten",
            ),
        ],
    ),
    "minimal": ("", [_exercise("Klimmzüge", "PULL_UP", "PULL_UP", sets=2, reps=6)]),
}


def documents() -> dict[str, dict[str, Any]]:
    """The documents the Garmin push builds for ``UNITS``."""
    with mock.patch.object(mapping, "catalogue_available", return_value=True):
        return {
            label: mapping.strength_workout(
                name=name,
                description=f"{WORKOUT_MARKER}\n{strength_structure.render(exercises)}",
                exercises=exercises,
            )
            for label, (name, exercises) in UNITS.items()
        }


def current_pin() -> tuple[int, str]:
    canonical = json.dumps(
        documents(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return mapping.PAYLOAD_VERSION, hashlib.sha256(canonical.encode()).hexdigest()


class PayloadVersionGuardTests(unittest.TestCase):
    def test_document_changes_come_with_a_payload_version_bump(self) -> None:
        version, digest = current_pin()
        pinned_version, pinned_digest = PINNED
        if digest != pinned_digest:
            self.assertNotEqual(
                version,
                pinned_version,
                "The Garmin strength workout document changed but PAYLOAD_VERSION "
                f"is still {version}. Bump PAYLOAD_VERSION in "
                "backend/providers/garmin_strength_workout.py so units sent in the "
                "old form show as changed, then re-pin with "
                "`python -m tests.test_garmin_payload_version_guard`.",
            )
        self.assertEqual(
            (version, digest),
            (pinned_version, pinned_digest),
            "PAYLOAD_VERSION and the document hash must be pinned together: "
            "update PINNED to the pair printed by "
            "`python -m tests.test_garmin_payload_version_guard`.",
        )

    def test_the_fixed_documents_cover_the_document_features(self) -> None:
        steps = [
            step
            for document in documents().values()
            for segment in document["workoutSegments"]
            for group in segment["workoutSteps"]
            for step in group["workoutSteps"]
        ]
        self.assertEqual(
            {"warmup", "interval", "rest"},
            {step["stepType"]["stepTypeKey"] for step in steps},
        )
        self.assertEqual(
            {40.0, 62.5, 100.0, 20.0, 60.0},
            {step["weightValue"] for step in steps if "weightValue" in step},
        )
        self.assertIn("2 RIR · nicht bis zum Muskelversagen", str(documents()))

    def test_the_pinned_version_is_part_of_the_unit_fingerprint(self) -> None:
        from backend.planning.push_state import garmin_fingerprint

        unit = {
            "sport": "WeightTraining",
            "date": "2026-11-09",
            "strength_structure": [{"name": "Kniebeuge", "sets": 3, "reps": 5}],
        }
        before = garmin_fingerprint(unit)
        with mock.patch(
            "backend.planning.push_state.PAYLOAD_VERSION", mapping.PAYLOAD_VERSION + 1
        ):
            after = garmin_fingerprint(unit)
        self.assertIsNotNone(before)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    print(f"PINNED: Final = {current_pin()!r}")
