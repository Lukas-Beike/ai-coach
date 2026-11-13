from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.athlete.equipment import EquipmentService
from backend.athlete.measurements import number
from backend.errors import AppError


class EquipmentDependencyTests(unittest.TestCase):
    def test_assignment_uses_injected_session_summaries(self) -> None:
        read_summaries = Mock(return_value=())
        service = EquipmentService(MagicMock(), read_summaries, Mock(), Mock())
        with (
            patch(
                "backend.athlete.equipment.canonical_store.live_session_id",
                return_value=None,
            ),
            self.assertRaises(AppError) as raised,
        ):
            service.assign({"activity_id": "synthetic", "equipment_id": None})
        self.assertEqual(raised.exception.status, 404)
        read_summaries.assert_called_once_with()

    def test_usage_numbers_reject_invalid_values_and_preserve_zero(self) -> None:
        for value in (True, False, "12", None, -1, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertIsNone(number(value))
        self.assertEqual(number(0), 0.0)
        self.assertEqual(number(12.5), 12.5)


if __name__ == "__main__":
    unittest.main()
