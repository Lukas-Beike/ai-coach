from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

from backend.errors import AppError
from backend.privacy import (
    PRIVACY_DELETE_CONFIRMATION_TEXT,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)

try:
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_registry import BACKEND_ROOT


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

    def test_missing_or_wrong_confirmation_fails_before_any_dependency_access(
        self,
    ) -> None:
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
        self.assertIn(
            "DELETE FROM nutrition_templates",
            [call.args[0] for call in db.execute.call_args_list],
        )
        self.assertIn(
            "DELETE FROM nutrition_products",
            [call.args[0] for call in db.execute.call_args_list],
        )
        dependencies.maintenance_gate.restore.assert_called_once_with()
        self.assertEqual(dependencies.database_manager.unit_of_work.call_count, 2)
        dependencies.planning_revision_service.mark_reset_pending.assert_called_once_with()


class PrivacyDeleteDialogTextContractTests(unittest.TestCase):
    """The dialog must show the exact text the backend requires."""

    REPO_ROOT = Path(__file__).resolve().parents[1]

    def test_settings_dialog_shows_the_backend_confirmation_constant(self) -> None:
        privacy_source = (BACKEND_ROOT / "privacy.py").read_text(encoding="utf-8")
        settings_source = (self.REPO_ROOT / "public" / "settings.js").read_text(
            encoding="utf-8"
        )

        match = re.search(
            r'^PRIVACY_DELETE_CONFIRMATION_TEXT = "([^"]+)"$',
            privacy_source,
            re.MULTILINE,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "LOKALE DATEN LÖSCHEN")
        self.assertIn(
            '"confirmation_text": PRIVACY_DELETE_CONFIRMATION_TEXT',
            privacy_source,
        )
        # settings.js takes the required text from the preview, so the dialog
        # cannot drift from the backend constant.
        self.assertIn("expectedText: preview.confirmation_text", settings_source)
        self.assertIn(
            'api("/api/privacy/delete/preview")',
            settings_source,
        )
        self.assertIn(
            'secondaryAction: { label: "Erst Backup erstellen", onClick: downloadDatabaseBackup }',
            settings_source,
        )


if __name__ == "__main__":
    unittest.main()
