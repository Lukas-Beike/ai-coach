"""Build context and Git ignore contracts for private and generated files."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {"." + "env", "data" + "/"}


def entries(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class IgnoreFileTests(unittest.TestCase):
    def test_docker_build_context_excludes_secrets_and_runtime_data(self):
        self.assertTrue(PRIVATE <= entries(".dockerignore"))

    def test_local_coverage_data_is_not_committed(self):
        self.assertTrue({".coverage", ".coverage.*"} <= entries(".gitignore"))


if __name__ == "__main__":
    unittest.main()
