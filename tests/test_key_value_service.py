from contextlib import contextmanager
import unittest
from unittest.mock import Mock

from backend.db.key_value import KeyValueService


class KeyValueServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = object()

        class Database:
            @contextmanager
            def unit_of_work(inner_self):
                yield self.db

        self.repository = Mock()
        self.service = KeyValueService(Database(), self.repository)

    def test_get_reads_inside_database_unit_of_work(self):
        self.repository.get.return_value = "stored"

        self.assertEqual(self.service.get("setting"), "stored")

        self.repository.get.assert_called_once_with(self.db, "setting")

    def test_set_writes_inside_database_unit_of_work(self):
        self.service.set("setting", "value")

        self.repository.set.assert_called_once_with(self.db, "setting", "value")


if __name__ == "__main__":
    unittest.main()
