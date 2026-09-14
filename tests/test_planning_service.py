import json
import sqlite3
import unittest

from backend.planning.service import update_plan_bounds


class PlanningServiceTests(unittest.TestCase):
    def test_plan_bounds_update_uses_caller_transaction_and_records_change(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE planned_units (payload TEXT)")
        db.execute("INSERT INTO planned_units VALUES (?)", (json.dumps({"plan_id": "p1", "date": "2026-01-03"}),))
        db.execute("INSERT INTO planned_units VALUES (?)", (json.dumps({"plan_id": "p1", "date": "2026-01-01"}),))
        plan = {"id": "p1", "name": "Base", "goal": "", "status": "planned", "start_date": "2026-01-02", "end_date": "2026-01-02"}
        updates = []
        changes = []
        update_plan_bounds(
            db, {"p1"}, get_plan=lambda _db, _id: plan,
            update_plan=lambda *args: updates.append(args),
            record_change=lambda *args, **kwargs: changes.append((args, kwargs)),
            now=lambda: "2026-01-04T00:00:00+00:00",
        )
        self.assertEqual(updates[0][4:6], ("2026-01-01", "2026-01-03"))
        self.assertEqual(changes[0][0][1:4], ("training_plan", "p1", "update"))
        db.close()


if __name__ == "__main__":
    unittest.main()
