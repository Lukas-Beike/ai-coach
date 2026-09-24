from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock

from backend.errors import AppError
from backend.privacy import (
    PRIVACY_DELETE_CONFIRMATION_TEXT,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)


class PrivacyDeleteConfirmationTests(unittest.TestCase):
    def service(self) -> tuple[PrivacyDeleteService, PrivacyDeleteDependencies]:
        dependencies = PrivacyDeleteDependencies(
            database_manager=MagicMock(),
            database_lock=MagicMock(),
            key_value_repository=Mock(),
            maintenance_gate=MagicMock(),
            planning_revision_service=Mock(),
            openai_client=Mock(),
            logger=Mock(),
        )
        return PrivacyDeleteService(dependencies), dependencies

    def test_missing_or_wrong_confirmation_fails_before_any_dependency_access(self) -> None:
        for confirmation in (None, "wrong"):
            with self.subTest(confirmation=confirmation):
                service, dependencies = self.service()

                with self.assertRaises(AppError) as caught:
                    service.delete(confirmation)

                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(
                    caught.exception.message,
                    "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden.",
                )
                dependencies.maintenance_gate.restore.assert_not_called()
                dependencies.database_manager.unit_of_work.assert_not_called()
                dependencies.openai_client.delete_conversation.assert_not_called()
                dependencies.planning_revision_service.mark_reset_pending.assert_not_called()

    def test_exact_confirmation_reaches_existing_local_deletion(self) -> None:
        service, dependencies = self.service()
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"count": 0}
        dependencies.database_manager.unit_of_work.return_value.__enter__.return_value = db
        dependencies.key_value_repository.get.return_value = ""

        result = service.delete(PRIVACY_DELETE_CONFIRMATION_TEXT)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["local_data_deleted"])
        dependencies.maintenance_gate.restore.assert_called_once_with()
        self.assertEqual(dependencies.database_manager.unit_of_work.call_count, 2)
        dependencies.planning_revision_service.mark_reset_pending.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
