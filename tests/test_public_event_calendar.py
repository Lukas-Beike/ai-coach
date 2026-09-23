import sqlite3
import unittest

from backend.calendar.public_events import list_candidates, list_sources, state


class PublicEventCalendarTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE public_event_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                last_sync_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE public_event_candidates (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                uid TEXT NOT NULL,
                name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                sport TEXT NOT NULL,
                distance TEXT NOT NULL,
                location TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL,
                imported_competition_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.db.executemany(
            "INSERT INTO public_event_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "source-old",
                    "Old Source",
                    "https://old.invalid",
                    None,
                    None,
                    "a",
                    "2026-01-01",
                ),
                (
                    "source-new",
                    "New Source",
                    "https://new.invalid",
                    None,
                    None,
                    "b",
                    "2026-02-01",
                ),
            ],
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def insert_candidates(self, count):
        self.db.executemany(
            "INSERT INTO public_event_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"candidate-{index:03d}",
                    "source-new" if index % 2 else "source-old",
                    f"uid-{index:03d}",
                    f"Event {index:03d}",
                    f"2026-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
                    "Run",
                    "10 km",
                    "Town",
                    "https://event.invalid",
                    "Synthetic event",
                    None,
                    "created",
                    "updated",
                )
                for index in range(count)
            ],
        )
        self.db.commit()

    def test_sources_are_projected_and_sorted_by_updated_at_descending(self):
        rows = list_sources(self.db)

        self.assertEqual(["source-new", "source-old"], [row["id"] for row in rows])
        self.assertEqual(
            {
                "id",
                "name",
                "url",
                "last_sync_at",
                "last_error",
                "created_at",
                "updated_at",
            },
            set(rows[0]),
        )

    def test_candidates_join_source_name_and_project_exact_fields(self):
        self.insert_candidates(3)

        rows = list_candidates(self.db)

        self.assertEqual(
            ["candidate-000", "candidate-001", "candidate-002"],
            [row["id"] for row in rows],
        )
        self.assertEqual(
            ["Old Source", "New Source", "Old Source"],
            [row["source_name"] for row in rows],
        )
        self.assertEqual(
            {
                "id",
                "source_id",
                "source_name",
                "uid",
                "name",
                "event_date",
                "sport",
                "distance",
                "location",
                "url",
                "description",
                "imported_competition_id",
                "created_at",
                "updated_at",
            },
            set(rows[0]),
        )

    def test_limit_is_clamped_at_one_and_five_hundred(self):
        self.insert_candidates(501)

        self.assertEqual(1, len(list_candidates(self.db, 0)))
        self.assertEqual(500, len(list_candidates(self.db, 501)))

    def test_default_limit_is_one_hundred(self):
        self.insert_candidates(101)

        self.assertEqual(100, len(list_candidates(self.db)))

    def test_invalid_limit_conversion_errors_propagate(self):
        with self.assertRaises(ValueError):
            list_candidates(self.db, "invalid")
        with self.assertRaises(TypeError):
            list_candidates(self.db, None)

    def test_state_has_exact_shape_and_default_candidate_limit(self):
        self.insert_candidates(101)

        result = state(self.db)

        self.assertEqual({"sources", "candidates"}, set(result))
        self.assertEqual(
            ["source-new", "source-old"], [row["id"] for row in result["sources"]]
        )
        self.assertEqual(100, len(result["candidates"]))
        self.assertEqual("Old Source", result["candidates"][0]["source_name"])


if __name__ == "__main__":
    unittest.main()
