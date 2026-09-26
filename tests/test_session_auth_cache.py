from __future__ import annotations

import threading
import unittest
from dataclasses import replace

from backend.config import Config
from backend.http_api.auth import SessionAuthServiceCache
from backend.http_api.rate_limit import RateLimiter


class SessionAuthServiceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = SessionAuthServiceCache()
        self.lock = threading.RLock()
        self.manager = object()
        self.config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="",
            openai_model="gpt-6-luna",
            gemini_api_key="",
            gemini_model="",
            ai_provider="openai",
            intervals_api_key="",
            intervals_athlete_id="",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="synthetic-password",
            secure_cookies=False,
            data_retention_days=30,
        )
        self.rate_limiter = RateLimiter()

    def resolve(self, manager=None, config=None):
        return self.cache.get(
            self.manager if manager is None else manager,
            self.lock,
            self.config if config is None else config,
            True,
            self.rate_limiter,
        )

    def test_reuses_service_until_manager_or_security_config_changes(self) -> None:
        first = self.resolve()
        self.assertIs(first, self.resolve())

        new_manager = object()
        second = self.resolve(manager=new_manager)
        self.assertIsNot(first, second)
        self.assertIs(second, self.resolve(manager=new_manager))

        changed_config = replace(self.config, secure_cookies=True)
        third = self.resolve(manager=new_manager, config=changed_config)
        self.assertIsNot(second, third)
        self.assertIs(third, self.resolve(manager=new_manager, config=changed_config))


if __name__ == "__main__":
    unittest.main()
