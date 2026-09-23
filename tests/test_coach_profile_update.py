"""Direct Coach profile authorization and optimistic-update regressions."""

import threading
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from backend.coach.profile_update import CoachProfileUpdateService
from backend.errors import AppError


class CoachProfileUpdateTests(unittest.TestCase):
    def setUp(self):
        self.profile = Mock()
        self.profile.get.return_value = {"name": "Athlete", "goals": "Current"}
        self.profile.save.side_effect = lambda updated: updated
        self.manager = Mock()

        @contextmanager
        def unit_of_work():
            yield object()

        self.manager.unit_of_work.side_effect = unit_of_work
        self.service = CoachProfileUpdateService(
            self.profile, self.manager, threading.RLock()
        )
        self.intent = {
            "operation": "update_profile", "target_system": "local",
            "authorization_scope": ["local_profile"],
        }

    def test_authorization_precedes_profile_read_and_write(self):
        with self.assertRaises(AppError) as raised:
            self.service.apply({"changes": []}, {"authorization_scope": []})
        self.assertEqual(raised.exception.status, 403)
        self.profile.get.assert_not_called()
        self.profile.save.assert_not_called()

    def test_later_field_conflict_aborts_entire_batch(self):
        changes = [
            {"field": "name", "expected_value": "Athlete", "value": "Updated"},
            {"field": "goals", "expected_value": "Stale", "value": "New"},
        ]
        with self.assertRaises(AppError) as raised:
            self.service.apply({"changes": changes}, self.intent)
        self.assertEqual(raised.exception.reason, "profile_conflict")
        self.profile.save.assert_not_called()

    def test_valid_batch_saves_only_selected_fields(self):
        result = self.service.apply(
            {"changes": [{"field": "name", "expected_value": "Athlete", "value": "Updated"}]},
            self.intent,
        )
        self.assertEqual(result["updated_fields"], ["name"])
        self.assertEqual(result["profile"], {"name": "Updated", "goals": "Current"})
        self.profile.save.assert_called_once_with({"name": "Updated", "goals": "Current"})


if __name__ == "__main__":
    unittest.main()
