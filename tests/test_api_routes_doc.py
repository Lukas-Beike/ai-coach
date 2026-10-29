"""Keep docs/api-routes.md in step with the routes the HTTP API registers.

Routes are read as text: the /api string literals in backend/http_api and the
manual and full-resync paths of the provider descriptors. Nothing is imported.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP_API = ROOT / "backend" / "http_api"
SOURCES = (*sorted(HTTP_API.glob("*.py")), ROOT / "backend/providers/descriptors.py")
ROUTE_LITERAL = re.compile(r'"(/api/[a-z0-9/_-]*[a-z0-9])"')
DOC_ROUTE = re.compile(r"`(?:(?:GET|POST|PUT) )?(/api/[^`\s]+)`")
NUTRITION = "nutrition.py"

# Documented routes no plain literal registers, with the source text that does.
REGISTERED_ELSEWHERE = {
    # Built from the nutrition path constants.
    "/api/nutrition/entry/delete": (NUTRITION, 'f"{NUTRITION_ENTRY_PATH}/delete"'),
    "/api/nutrition/products/lookup": (
        NUTRITION,
        'f"{NUTRITION_PRODUCTS_PATH}/lookup"',
    ),
    "/api/nutrition/products/extract": (
        NUTRITION,
        'f"{NUTRITION_PRODUCTS_PATH}/extract"',
    ),
    "/api/nutrition/products/archive": (
        NUTRITION,
        'f"{NUTRITION_PRODUCTS_PATH}/archive"',
    ),
    "/api/nutrition/products/database/delete": (
        NUTRITION,
        'f"{NUTRITION_PRODUCTS_PATH}/database/delete"',
    ),
    # Matched by a prefix and suffix around the provider segment.
    "/api/providers/{id}/check": (
        "provider_connections.py",
        'CHECK_PREFIX = "/api/providers/"',
    ),
    # Matched by regular expressions over the id segment.
    "/api/activities/{id}": ("sync_get.py", '"^/api/activities/([^/]+)$"'),
    "/api/activities/{id}/feedback": (
        "feedback_post.py",
        '"/api/activities/([^/]+)/feedback"',
    ),
    "/api/sync/jobs/{id}": ("sync_get.py", '"^/api/sync/jobs/([0-9a-f-]+)$"'),
    "/api/sync/jobs/{id}/resolve": (
        "sync_commands.py",
        '"^/api/sync/jobs/([0-9a-f-]+)/resolve$"',
    ),
}
# Former aliases the document names as no longer registered.
RETIRED_ALIASES = {"/api/logs/clear", "/api/diagnostics/clear"}


class ApiRoutesDocTests(unittest.TestCase):
    def setUp(self):
        self.registered = {
            route
            for source in SOURCES
            for route in ROUTE_LITERAL.findall(source.read_text(encoding="utf-8"))
        }
        doc = (ROOT / "docs" / "api-routes.md").read_text(encoding="utf-8")
        self.documented = set(DOC_ROUTE.findall(doc))

    def test_every_registered_route_is_documented(self):
        self.assertEqual(sorted(self.registered - self.documented), [])

    def test_every_documented_route_is_registered(self):
        known = self.registered | set(REGISTERED_ELSEWHERE) | RETIRED_ALIASES
        self.assertEqual(sorted(self.documented - known), [])

    def test_exceptions_stay_documented_and_backed_by_their_source(self):
        self.assertEqual(sorted(self.registered & set(REGISTERED_ELSEWHERE)), [])
        self.assertEqual(sorted(self.registered & RETIRED_ALIASES), [])
        for route, (module, source_text) in REGISTERED_ELSEWHERE.items():
            with self.subTest(route=route):
                self.assertIn(route, self.documented)
                source = (HTTP_API / module).read_text(encoding="utf-8")
                self.assertIn(source_text, source)
        self.assertLessEqual(RETIRED_ALIASES, self.documented)


if __name__ == "__main__":
    unittest.main()
