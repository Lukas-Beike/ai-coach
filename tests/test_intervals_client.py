import sys
import types
import unittest
from unittest.mock import patch

from backend.providers.intervals_client import _app


class IntervalsClientTests(unittest.TestCase):
    def test_entrypoint_mode_uses_active_main_module(self):
        active = types.SimpleNamespace(initialise_database=object())
        with patch.dict(sys.modules, {"__main__": active}):
            self.assertIs(_app(), active)


if __name__ == "__main__":
    unittest.main()
