"""Parity and mutation isolation for the smaller disposable staging fixture."""

import json
from datetime import datetime, time
from unittest.mock import patch

from test_fixture_standard_data import StandardFixtureTestCase, fixture_runtime


def _planning_records(server):
    """Compare all domain fields, excluding per-database IDs and write times."""

    def comparable(rows):
        return sorted(
            [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"id", "local_id", "created_at", "updated_at"}
                }
                for row in rows
            ],
            key=lambda row: json.dumps(row, sort_keys=True),
        )

    with server.database_manager().unit_of_work() as db:
        units = [
            json.loads(row["payload"])
            for row in db.execute("SELECT payload FROM planned_units").fetchall()
        ]
        events = [
            dict(row)
            for row in db.execute("SELECT * FROM external_calendar_events").fetchall()
        ]
    return {
        "units": comparable(units),
        "competitions": comparable(server.PLANNING_DATA.competition().list(100)),
        "calendar": comparable(events),
    }


class FixturePlanningParityTests(StandardFixtureTestCase):
    def test_planning_seed_matches_complete_demo_and_isolates_mutated_cases(self):
        expected = None
        expected_staged = None
        # The first case executes the real complete seed. Each subsequent case
        # starts from its own database after the preceding case deletes its data.
        for case in ("complete", "planning", "planning-after-mutation"):
            with self.subTest(case=case):
                with (
                    self._temporary_fixture_database(
                        "fixture-planning-parity-"
                    ) as server,
                    patch.dict("os.environ", {"FIXTURE_AUTO_SEED": "0"}),
                    patch.object(
                        server.ATHLETE_CLOCK,
                        "now",
                        return_value=datetime.combine(self.today, time(10, 0)),
                    ),
                ):
                    fixture_runtime.initialise_fixture()
                    self.assertEqual(
                        _planning_records(server),
                        {"units": [], "competitions": [], "calendar": []},
                    )
                    if case == "complete":
                        fixture_runtime.seed_preview_demo()
                    else:
                        fixture_runtime.seed_fixture_planning_calendar(self.today)
                    records = _planning_records(server)
                    fixture_runtime.stage_fixture_artifact()
                    with server.database_manager().unit_of_work() as db:
                        staged = json.loads(
                            db.execute(
                                "SELECT payload FROM coach_plan_artifacts WHERE id=?",
                                (fixture_runtime.artifact["artifact_id"],),
                            ).fetchone()["payload"]
                        )
                        if case != "complete":
                            # The optimized path must actually omit unrelated
                            # histories rather than delegate to the demo seed.
                            for table in (
                                "nutrition_logs",
                                "activity_sessions",
                                "observations",
                            ):
                                self.assertEqual(
                                    db.execute(
                                        f"SELECT COUNT(*) AS n FROM {table}"
                                    ).fetchone()["n"],
                                    0,
                                )
                        for table in (
                            "planned_units",
                            "competitions",
                            "external_calendar_events",
                        ):
                            db.execute(f"DELETE FROM {table}")
                    self.assertEqual(
                        _planning_records(server),
                        {"units": [], "competitions": [], "calendar": []},
                    )
                if case == "complete":
                    expected = records
                    expected_staged = staged
                    self.assertEqual(
                        {key: len(value) for key, value in expected.items()},
                        {"units": 8, "competitions": 4, "calendar": 7},
                    )
                else:
                    self.assertEqual(records, expected)
                    self.assertEqual(staged, expected_staged)
