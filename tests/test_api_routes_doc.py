"""Keep the generated route table in docs/api-routes.md current.

Run ``python tests/test_api_routes_doc.py --write`` to regenerate it. Every route
handler's docstring is a purpose line followed by its ``Request:``, ``Response:``
and ``Errors:`` paragraphs.
"""

import inspect
import re
import sys
import unittest
from pathlib import Path

# The repository root, for running this file as a script with --write.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server_test_support import server

from backend.http_api.route_table import CONTRACT_LABELS, route_reference

DOC = Path(__file__).resolve().parents[1] / "docs" / "api-routes.md"
BEGIN = "<!-- BEGIN GENERATED ROUTES -->\n"
END = "<!-- END GENERATED ROUTES -->\n"
PROSE_ROUTE = re.compile(r"`(GET|POST|PUT) (/api/[^`\s]+)`")
# Former aliases the document names as no longer registered.
RETIRED_ALIASES = {"/api/logs/clear", "/api/diagnostics/clear"}


def _generated(document: str) -> str:
    return document.split(BEGIN, 1)[1].split(END, 1)[0]


def _rendered() -> str:
    return route_reference(server.HTTP_API.route_table.routes)


class ApiRoutesDocTests(unittest.TestCase):
    def test_generated_route_table_is_current(self):
        self.assertEqual(
            _generated(DOC.read_text(encoding="utf-8")),
            _rendered(),
            "Regenerate with: python tests/test_api_routes_doc.py --write",
        )

    def test_every_route_handler_states_its_purpose_and_contract(self):
        def contract(route):
            paragraphs = (inspect.getdoc(route.handle) or "").split("\n\n")
            return [p.split(" ", 1)[0] for p in paragraphs[1:4]]

        self.assertEqual(
            [
                f"{route.method} {route.path}"
                for route in server.HTTP_API.route_table.routes
                if not inspect.getdoc(route.handle)
                or contract(route) != list(CONTRACT_LABELS)
            ],
            [],
        )

    def test_routes_named_in_the_prose_are_registered(self):
        document = DOC.read_text(encoding="utf-8")
        registered = {
            (route.method, re.sub(r"\{(\w+)(?::[^}]+)?\}", "{id}", route.path))
            for route in server.HTTP_API.route_table.routes
        }
        named = {
            (method, re.sub(r"\{\w+\}", "{id}", path))
            for method, path in PROSE_ROUTE.findall(document)
        }
        self.assertTrue(named)
        self.assertEqual(sorted(named - registered), [])
        for alias in RETIRED_ALIASES:
            self.assertIn(f"`{alias}`", document)
            self.assertNotIn(alias, {path for _, path in registered})


if __name__ == "__main__":
    if "--write" in sys.argv:
        document = DOC.read_text(encoding="utf-8")
        before, rest = document.split(BEGIN, 1)
        after = rest.split(END, 1)[1]
        DOC.write_text(before + BEGIN + _rendered() + END + after, encoding="utf-8")
    else:
        unittest.main()
