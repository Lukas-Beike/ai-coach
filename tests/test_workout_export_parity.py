"""Golden parity for Intervals.icu workout payloads and their input normalization.

The fixture ``tests/fixtures/workout_export_parity.json`` is compact. It stores
the case count, canonical-JSON digests over the ordered outcome records of the
whole matrix and of its payload subset, a digest per block of records, and a
set of representative records verbatim. The records were recorded from the base
commit f2b417dd. Inputs live in ``tests/workout_export_parity_matrix.py``.

A mismatch names the first differing representative case. Without one, it names
the first differing block of records.
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


def _outcome(call, *args, **kwargs):
    try:
        return {"ok": call(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 - failures are recorded behavior too
        attrs = {key: repr(value) for key, value in sorted(vars(exc).items())}
        return {
            "error": {"type": type(exc).__name__, "message": str(exc), "attrs": attrs}
        }


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _as_recorded(record):
    """Round-trip through JSON so records compare like the stored fixture."""
    return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))


def _facade_payload(workout_id, workout):
    return planning_workouts.workout_event_payload(workout_id, workout, today=TODAY)


def _port_payload(workout_id, workout):
    export = IntervalsWorkoutExport(Mock())
    return export.serialize(
        workout_id, build_planned_workout_export(workout, today=TODAY)
    )


def _normalize(draft):
    return planning_workouts.normalize_workout(draft, today=TODAY)


def _facade_records():
    records = []
    for case_id, workout_id, workout in matrix.payload_cases():
        outcome = _outcome(_facade_payload, workout_id, workout)
        records.append(_as_recorded({"case_id": f"payload/{case_id}", **outcome}))
    for case_id, draft in matrix.normalize_cases():
        outcome = _outcome(_normalize, draft)
        records.append(_as_recorded({"case_id": f"normalize/{case_id}", **outcome}))
    for case_id, value in matrix.sport_cases():
        outcome = _outcome(planning_workouts.intervals_workout_sport, value)
        records.append(_as_recorded({"case_id": f"sport/{case_id}", **outcome}))
    return records


def _port_payload_records():
    records = []
    for case_id, workout_id, workout in matrix.payload_cases():
        outcome = _outcome(_port_payload, workout_id, workout)
        records.append(_as_recorded({"case_id": f"payload/{case_id}", **outcome}))
    return records


def _first_representative_mismatch(fixture, actual_by_id, prefix=""):
    for expected in fixture["representative"]:
        case_id = expected["case_id"]
        if case_id.startswith(prefix) and actual_by_id.get(case_id) != expected:
            return case_id
    return None


def _first_block_mismatch(fixture, actual_records):
    size = fixture["block_size"]
    for block, expected in enumerate(fixture["block_sha256"]):
        chunk = actual_records[block * size : (block + 1) * size]
        if _digest(chunk) != expected:
            return chunk[0]["case_id"], chunk[-1]["case_id"]
    return None


def _describe_facade_mismatch(fixture, actual_records):
    actual_by_id = {record["case_id"]: record for record in actual_records}
    case_id = _first_representative_mismatch(fixture, actual_by_id)
    if case_id is not None:
        return f"first differing representative case: {case_id}"
    span = _first_block_mismatch(fixture, actual_records)
    if span is not None:
        return (
            "first differing block, not a representative case, spans "
            f"{span[0]} .. {span[1]}"
        )
    return "digest differs although every block matches (canonicalisation drift)"


class WorkoutExportParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.records = _facade_records()

    def test_fixture_is_pinned_to_matrix_date_and_case_count(self):
        self.assertEqual(self.fixture["schema"], 2)
        self.assertEqual(self.fixture["today"], TODAY.isoformat())
        self.assertEqual(self.fixture["today"], matrix.TODAY_ISO)
        self.assertEqual(self.fixture["case_count"], len(self.records))
        case_ids = [record["case_id"] for record in self.records]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertLessEqual(
            {record["case_id"] for record in self.fixture["representative"]},
            set(case_ids),
        )

    def test_planning_facade_matches_golden_for_every_case(self):
        if _digest(self.records) != self.fixture["sha256"]:
            self.fail(
                "planning facade drifted from the golden: "
                + _describe_facade_mismatch(self.fixture, self.records)
            )

    def test_export_port_payload_matches_golden_for_every_payload_case(self):
        port_records = _port_payload_records()
        if _digest(port_records) != self.fixture["payload_sha256"]:
            actual_by_id = {record["case_id"]: record for record in port_records}
            case_id = _first_representative_mismatch(
                self.fixture, actual_by_id, prefix="payload/"
            )
            detail = (
                f"first differing representative case: {case_id}"
                if case_id is not None
                else "payload digest differs outside the representative cases"
            )
            self.fail("export port payload drifted from the golden: " + detail)


if __name__ == "__main__":
    unittest.main()
