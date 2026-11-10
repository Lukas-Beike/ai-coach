"""Static guards for the structured-log contract.

``JsonLogFormatter`` serializes only a record's ``event`` and ``context``
attributes, so every other ``extra`` key is silently dropped, and only loggers
below ``intervals_coach`` reach the configured file and stream handlers.
"""

from __future__ import annotations

import ast
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = "intervals_coach"
ALLOWED_EXTRA_KEYS = frozenset({"event", "context"})
# Open PR #1917 (#1888 C8) moves these call sites under "context" in its own
# change; remove this entry once it has merged.
PENDING_EXTRA_FIXES = frozenset({"backend/coach/context.py"})


def _sources() -> Iterator[tuple[str, ast.Module]]:
    paths = [ROOT / "server.py", *sorted((ROOT / "backend").rglob("*.py"))]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        yield relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def extra_violations(relative: str, tree: ast.AST) -> list[str]:
    """Return ``extra=`` arguments that carry a key outside event/context."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "extra":
                continue
            where = f"{relative}:{node.lineno}"
            if not isinstance(keyword.value, ast.Dict):
                found.append(f"{where} extra is not a dict literal")
                continue
            for key in keyword.value.keys:
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    found.append(f"{where} extra has a non-literal key")
                elif key.value not in ALLOWED_EXTRA_KEYS:
                    found.append(f"{where} extra key {key.value!r}")
    return found


def logger_violations(relative: str, tree: ast.AST) -> list[str]:
    """Return ``getLogger`` calls that name a logger outside ``intervals_coach``."""
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getLogger"
        ):
            continue
        name = node.args[0] if node.args else None
        inside = (
            isinstance(name, ast.Constant)
            and isinstance(name.value, str)
            and (name.value == LOG_ROOT or name.value.startswith(LOG_ROOT + "."))
        )
        if not inside:
            found.append(f"{relative}:{node.lineno} logger outside {LOG_ROOT}")
    return found


def _parse(source: str) -> ast.Module:
    return ast.parse(source)


class LogExtraGuardTests(unittest.TestCase):
    def test_extra_dicts_only_use_event_and_context(self) -> None:
        violations = [
            violation
            for relative, tree in _sources()
            if relative not in PENDING_EXTRA_FIXES
            for violation in extra_violations(relative, tree)
        ]

        self.assertEqual(
            violations,
            [],
            "Put log fields under extra={'event': ..., 'context': {...}}.",
        )

    def test_guard_flags_a_new_top_level_extra_key(self) -> None:
        tree = _parse(
            "log.error('x', extra={'event': 'e', 'error_class': 'E'})\n"
            "log.error('x', extra={'event': 'e', 'context': {'error_class': 'E'}})\n"
            "log.error('x', extra=fields)\n"
        )

        self.assertEqual(
            extra_violations("sample.py", tree),
            [
                "sample.py:1 extra key 'error_class'",
                "sample.py:3 extra is not a dict literal",
            ],
        )


class LoggerHierarchyGuardTests(unittest.TestCase):
    def test_every_module_logger_is_inside_the_configured_hierarchy(self) -> None:
        violations = [
            violation
            for relative, tree in _sources()
            for violation in logger_violations(relative, tree)
        ]

        self.assertEqual(
            violations,
            [],
            f"Use logging.getLogger({LOG_ROOT!r}); other names have no handler.",
        )

    def test_guard_flags_module_name_loggers(self) -> None:
        tree = _parse(
            "import logging\n"
            "a = logging.getLogger(__name__)\n"
            "b = logging.getLogger('other')\n"
            "c = logging.getLogger('intervals_coach')\n"
            "d = logging.getLogger('intervals_coach.sync')\n"
        )

        self.assertEqual(
            logger_violations("sample.py", tree),
            [
                "sample.py:2 logger outside intervals_coach",
                "sample.py:3 logger outside intervals_coach",
            ],
        )


if __name__ == "__main__":
    unittest.main()
