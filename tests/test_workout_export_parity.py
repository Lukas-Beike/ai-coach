"""Golden parity for Intervals.icu workout payloads and their input normalization.

The fixture holds canonical-JSON digests recorded from the planning code before
the export model refactor. Each matrix case, including errors with status,
message, and reason, must keep the same digest through the planning facade, and
every payload case must keep it through the export port as well. The inputs
live in ``tests/workout_export_parity_matrix.py``.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from backend.planning import workouts as planning_workouts
from backend.planning.workout_export import build_planned_workout_export
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from tests import workout_export_parity_matrix as matrix

FIXTURE = Path(__file__).parent / "fixtures" / "workout_export_parity.json"
TODAY = date(2026, 10, 12)


def _outcome(call, *args):
    try:
        return {"ok": call(*args)}
    except Exception as exc:  # noqa: BLE001 - failures are recorded behavior too
        attrs = {key: repr(value) for key, value in sorted(vars(exc).items())}
        return {
            "error": {"type": type(exc).__name__, "message": str(exc), "attrs": attrs}
        }


def _digest(record):
    text = json.dumps(record, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _facade_payload(workout_id, workout):
    return planning_workouts.workout_event_payload(workout_id, workout, today=TODAY)


def _port_payload(workout_id, workout):
    export = IntervalsWorkoutExport(Mock())
    return export.serialize(
        workout_id, build_planned_workout_export(workout, today=TODAY)
    )


def _normalize(draft):
    return planning_workouts.normalize_workout(draft, today=TODAY)


def _records(payload_call):
    records = {}
    for case_id, workout_id, workout in matrix.payload_cases():
        outcome = _outcome(payload_call, workout_id, workout)
        records[f"payload/{case_id}"] = _digest(outcome)
    for case_id, draft in matrix.normalize_cases():
        records[f"normalize/{case_id}"] = _digest(_outcome(_normalize, draft))
    for case_id, value in matrix.sport_cases():
        outcome = _outcome(planning_workouts.intervals_workout_sport, value)
        records[f"sport/{case_id}"] = _digest(outcome)
    return records


class WorkoutExportParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.today = fixture["today"]
        cls.expected = {case["id"]: case["sha256"] for case in fixture["cases"]}

    def test_fixture_is_pinned_to_matrix_date_and_case_ids(self):
        self.assertEqual(self.today, TODAY.isoformat())
        self.assertEqual(self.today, matrix.TODAY_ISO)
        self.assertEqual(set(_records(_facade_payload)), set(self.expected))

    def test_planning_facade_matches_golden_for_every_case(self):
        actual = _records(_facade_payload)
        mismatched = sorted(
            case_id
            for case_id in self.expected
            if actual.get(case_id) != self.expected[case_id]
        )
        self.assertEqual(mismatched, [])

    def test_export_port_payload_matches_golden_for_every_payload_case(self):
        actual = _records(_port_payload)
        mismatched = sorted(
            case_id
            for case_id, digest in self.expected.items()
            if case_id.startswith("payload/") and actual.get(case_id) != digest
        )
        self.assertEqual(mismatched, [])


if __name__ == "__main__":
    unittest.main()
