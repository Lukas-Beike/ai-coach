import sqlite3
import unittest
from datetime import date

from backend.athlete.checkins import (
    CHECKIN_SCORE_FIELDS,
    CHECKIN_TEXT_LIMITS,
    CheckinService,
    bounded_minutes,
    bounded_score,
    normalize_checkin,
)
from backend.db.repositories import CheckinRepository
from backend.errors import AppError

TODAY = date(2026, 8, 31)


class FakeManager:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE athlete_checkins ("
            "checkin_date TEXT PRIMARY KEY, soreness INTEGER, stress INTEGER, motivation INTEGER, "
            "session_rpe INTEGER, day_form TEXT, illness TEXT, pain TEXT, available_minutes INTEGER, "
            "availability_notes TEXT, notes TEXT, created_at TEXT, updated_at TEXT)"
        )
        self.commits = 0
        self.rollbacks = 0

    def unit_of_work(self):
        manager = self

        class UnitOfWork:
            def __enter__(self):
                return manager.connection

            def __exit__(self, exc_type, exc_value, traceback):
                if exc_type is None:
                    manager.connection.commit()
                    manager.commits += 1
                else:
                    manager.connection.rollback()
                    manager.rollbacks += 1
                return False

        return UnitOfWork()

    def close(self):
        self.connection.close()


class FailingCheckinRepository(CheckinRepository):
    def upsert(self, db, checkin):
        super().upsert(db, checkin)
        raise RuntimeError("synthetic write failure")


class RecordingCheckinRepository(CheckinRepository):
    def __init__(self):
        super().__init__(lambda: "2026-08-31T12:00:00+00:00")
        self.limits = []

    def list(self, db, limit=30):
        self.limits.append(limit)
        return []


class FailingListCheckinRepository(CheckinRepository):
    def list(self, db, limit=30):
        raise RuntimeError("synthetic read failure")


class AthleteCheckinTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.repository = CheckinRepository(lambda: "2026-08-31T12:00:00+00:00")
        self.service = CheckinService(self.manager, self.repository, lambda: TODAY)

    def tearDown(self):
        self.manager.close()

    def test_public_constants_match_checkin_contract(self):
        self.assertEqual(
            CHECKIN_SCORE_FIELDS, ("soreness", "stress", "motivation", "session_rpe")
        )
        self.assertEqual(
            CHECKIN_TEXT_LIMITS,
            {
                "day_form": 2000,
                "illness": 1000,
                "pain": 1000,
                "availability_notes": 2000,
                "notes": 4000,
            },
        )

    def test_bounded_score_accepts_empty_and_boundaries(self):
        self.assertIsNone(bounded_score(None))
        self.assertIsNone(bounded_score(""))
        self.assertEqual(bounded_score(0), 0)
        self.assertEqual(bounded_score("10"), 10)

    def test_bounded_score_rejects_non_integer_and_out_of_range_values(self):
        with self.assertRaisesRegex(
            AppError, "Lokale Feedback-Werte müssen ganze Zahlen sein"
        ):
            bounded_score("not-a-number")
        with self.assertRaisesRegex(
            AppError, "Lokale Feedback-Werte müssen zwischen 0 und 10 liegen"
        ):
            bounded_score(-1)
        with self.assertRaisesRegex(
            AppError, "Lokale Feedback-Werte müssen zwischen 0 und 10 liegen"
        ):
            bounded_score(11)

    def test_bounded_minutes_accepts_empty_and_boundaries(self):
        self.assertIsNone(bounded_minutes(None))
        self.assertIsNone(bounded_minutes(""))
        self.assertEqual(bounded_minutes(0), 0)
        self.assertEqual(bounded_minutes("1440"), 1440)

    def test_bounded_minutes_rejects_non_integer_and_out_of_range_values(self):
        with self.assertRaisesRegex(
            AppError, "Die verfügbare Trainingszeit muss eine ganze Zahl sein"
        ):
            bounded_minutes("not-a-number")
        with self.assertRaisesRegex(
            AppError,
            "Die verfügbare Trainingszeit muss zwischen 0 und 1440 Minuten liegen",
        ):
            bounded_minutes(-1)
        with self.assertRaisesRegex(
            AppError,
            "Die verfügbare Trainingszeit muss zwischen 0 und 1440 Minuten liegen",
        ):
            bounded_minutes(1441)

    def test_normalize_checkin_rejects_non_dict(self):
        with self.assertRaisesRegex(
            AppError, "Das lokale Feedback muss ein Objekt sein"
        ):
            normalize_checkin([], today=TODAY)

    def test_normalize_checkin_defaults_date_and_normalizes_values(self):
        result = normalize_checkin(
            {"soreness": "7", "available_minutes": "45", "day_form": "  Müde  "},
            today=TODAY,
        )
        self.assertEqual(result["checkin_date"], "2026-08-31")
        self.assertEqual(result["soreness"], 7)
        self.assertEqual(result["available_minutes"], 45)
        self.assertEqual(result["day_form"], "Müde")
        self.assertIsNone(result["stress"])

    def test_normalize_checkin_rejects_invalid_and_future_dates(self):
        with self.assertRaisesRegex(
            AppError, "Das Datum des lokalen Feedbacks ist ungültig"
        ):
            normalize_checkin({"checkin_date": "not-a-date"}, today=TODAY)
        with self.assertRaisesRegex(
            AppError, "Ein Tages-Check-in kann nicht in der Zukunft liegen"
        ):
            normalize_checkin({"checkin_date": "2026-09-01"}, today=TODAY)
        self.assertEqual(
            normalize_checkin({"checkin_date": "2026-08-30"}, today=TODAY)[
                "checkin_date"
            ],
            "2026-08-30",
        )

    def test_normalize_checkin_trims_and_limits_all_text_fields(self):
        value = {
            field: f"  {'x' * (limit + 1)}  "
            for field, limit in CHECKIN_TEXT_LIMITS.items()
        }
        result = normalize_checkin(value, today=TODAY)
        for field, limit in CHECKIN_TEXT_LIMITS.items():
            self.assertEqual(len(result[field]), limit)
            self.assertEqual(result[field], ("x" * (limit + 1))[:limit])

    def test_normalize_checkin_does_not_mutate_input(self):
        value = {
            "checkin_date": " 2026-08-30 ",
            "soreness": "7",
            "day_form": "  tired  ",
            "unknown": ["unchanged"],
        }
        original = {
            key: item.copy() if isinstance(item, list) else item
            for key, item in value.items()
        }
        normalize_checkin(value, today=TODAY)
        self.assertEqual(value, original)

    def test_list_clamps_limit(self):
        repository = RecordingCheckinRepository()
        service = CheckinService(self.manager, repository, lambda: TODAY)
        self.assertEqual(service.list(0), [])
        self.assertEqual(service.list(999), [])
        self.assertEqual(repository.limits, [1, 365])

    def test_save_upserts_and_returns_saved_row(self):
        result = self.service.save({"soreness": 7, "notes": " tired "})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checkin"]["checkin_date"], TODAY.isoformat())
        self.assertEqual(result["checkin"]["soreness"], 7)
        self.assertEqual(result["checkin"]["notes"], "tired")
        updated = self.service.save({"soreness": 3})
        self.assertEqual(updated["checkin"]["soreness"], 3)

    def test_save_uses_injected_local_date(self):
        service = CheckinService(
            self.manager, self.repository, lambda: date(2026, 8, 30)
        )
        result = service.save({"notes": "yesterday"})
        self.assertEqual(result["checkin"]["checkin_date"], "2026-08-30")

    def test_save_coach_rejects_non_dict(self):
        with self.assertRaisesRegex(
            AppError, "Der Tages-Check-in muss als Objekt gesendet werden"
        ):
            self.service.save_coach([])

    def test_save_coach_merges_omitted_and_minus_one_values(self):
        self.service.save(
            {
                "soreness": 8,
                "stress": 4,
                "available_minutes": 45,
                "day_form": "good",
                "notes": "keep",
            }
        )
        result = self.service.save_coach(
            {"soreness": -1, "stress": 6, "available_minutes": -1, "notes": ""}
        )
        saved = result["checkin"]
        self.assertTrue(result["stored_locally"])
        self.assertEqual(saved["soreness"], 8)
        self.assertEqual(saved["stress"], 6)
        self.assertEqual(saved["available_minutes"], 45)
        self.assertEqual(saved["notes"], "keep")
        self.assertEqual(saved["day_form"], "good")

    def test_context_limits_recent_and_uses_today(self):
        for offset in range(16):
            day = date(2026, 8, 31 - offset)
            self.service.save({"checkin_date": day.isoformat(), "notes": str(offset)})
        context = self.service.context()
        self.assertEqual(context["today"]["checkin_date"], TODAY.isoformat())
        self.assertEqual(len(context["recent"]), 14)
        self.assertEqual(
            context["scope"],
            "Only athlete-entered subjective feedback and constraints; wearable/provider values remain in their source sections.",
        )

    def test_repository_get_returns_focused_row(self):
        self.service.save({"notes": "found"})
        with self.manager.unit_of_work() as db:
            result = self.repository.get(db, TODAY.isoformat())
            missing = self.repository.get(db, "2026-01-01")
        self.assertEqual(result["notes"], "found")
        self.assertIsNone(missing)
        self.assertEqual(
            set(result),
            {
                "soreness",
                "stress",
                "motivation",
                "session_rpe",
                "day_form",
                "illness",
                "pain",
                "available_minutes",
                "availability_notes",
                "notes",
            },
        )

    def test_save_rolls_back_failed_upsert(self):
        failing = CheckinService(
            self.manager,
            FailingCheckinRepository(lambda: "2026-08-31T12:00:00+00:00"),
            lambda: TODAY,
        )
        with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
            failing.save({"notes": "fail"})
        self.assertEqual(self.manager.rollbacks, 1)
        with self.manager.unit_of_work() as db:
            self.assertEqual(self.repository.list(db, 365), [])

    def test_save_preserves_committed_upsert_when_followup_read_fails(self):
        repository = FailingListCheckinRepository(lambda: "2026-08-31T12:00:00+00:00")
        service = CheckinService(self.manager, repository, lambda: TODAY)
        with self.assertRaisesRegex(RuntimeError, "synthetic read failure"):
            service.save({"notes": "committed"})
        with self.manager.unit_of_work() as db:
            saved = self.repository.list(db, 365)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["notes"], "committed")


if __name__ == "__main__":
    unittest.main()
