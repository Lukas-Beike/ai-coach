"""Authenticated provider credential PUT route.

CSRF and session checks run in ``handler._do_PUT`` before dispatch. The
response carries status only and never echoes submitted values. The write is
deliberately not recorded in change history.
"""

from __future__ import annotations

from typing import Any

from backend.provider_credentials import ProviderCredentialService

CREDENTIALS_PATH = "/api/settings/credentials"


class CredentialsPutRoutes:
    """Dispatch provider credential writes through the credential service."""

    def __init__(self, credentials: ProviderCredentialService) -> None:
        self._credentials = credentials

    def handle(self, handler: Any, path: str) -> bool:
        if path != CREDENTIALS_PATH:
            return False
        result = self._credentials.update(handler.read_json())
        handler.send_json(200, result)
        return True
