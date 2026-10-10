import unittest
from unittest.mock import Mock

from backend.http_api.equipment_post import EquipmentPostRoutes


class EquipmentPostRoutesTests(unittest.TestCase):
    def test_maintenance_post_delegates_to_equipment_service(self):
        service = Mock()
        service.maintain.return_value = {"ok": True}
        handler = Mock()
        handler.read_json.return_value = {"equipment_id": "a", "date": "2026-10-07"}

        handled = EquipmentPostRoutes(lambda: service).handle(
            handler, "/api/equipment/maintenance"
        )

        self.assertTrue(handled)
        service.maintain.assert_called_once_with(
            {"equipment_id": "a", "date": "2026-10-07"}
        )
        handler.send_json.assert_called_once_with(200, {"ok": True})

    def test_other_paths_are_not_handled(self):
        handler = Mock()
        self.assertFalse(EquipmentPostRoutes(Mock()).handle(handler, "/api/other"))
        handler.read_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
