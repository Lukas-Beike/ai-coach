"""Module boundaries and imports in the server architecture."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .architecture_analysis import (
        parse_python as _parse,
    )
    from .architecture_analysis import (
        python_files as _python_files,
    )
    from .architecture_analysis import (
        runtime_import_cycles as _runtime_import_cycles,
    )
    from .architecture_analysis import (
        server_import_violations as _server_import_violations,
    )
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_analysis import (
        parse_python as _parse,
    )
    from architecture_analysis import (
        python_files as _python_files,
    )
    from architecture_analysis import (
        runtime_import_cycles as _runtime_import_cycles,
    )
    from architecture_analysis import (
        server_import_violations as _server_import_violations,
    )
    from architecture_registry import BACKEND_ROOT


class ServerModuleArchitectureTests(unittest.TestCase):
    def test_backend_does_not_import_or_reach_server_namespace(self) -> None:
        self.assertTrue(BACKEND_ROOT.is_dir(), "Backend source must be available")
        violations: list[str] = []
        for path in _python_files(BACKEND_ROOT):
            violations.extend(_server_import_violations(path, _parse(path)))
        self.assertEqual(
            [],
            violations,
            "Backend modules must not import or dynamically access server.py:\n"
            + "\n".join(violations),
        )

    def test_backend_has_no_eager_runtime_import_cycles(self) -> None:
        self.assertEqual([], _runtime_import_cycles(BACKEND_ROOT))

    def test_import_cycle_guard_ignores_type_only_and_function_local_imports(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend_root = Path(temporary) / "backend"
            backend_root.mkdir()
            (backend_root / "__init__.py").write_text("", encoding="utf-8")
            (backend_root / "first.py").write_text(
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from . import second\n"
                "def later():\n    from . import second\n",
                encoding="utf-8",
            )
            (backend_root / "second.py").write_text(
                "from . import first\n",
                encoding="utf-8",
            )
            self.assertEqual([], _runtime_import_cycles(backend_root))

            (backend_root / "first.py").write_text(
                "from . import second\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [("backend.first", "backend.second")],
                _runtime_import_cycles(backend_root),
            )


if __name__ == "__main__":
    unittest.main()
