from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nutrition_service_support import build_nutrition_services
from support import temp_database

from backend.errors import AppError
from backend.nutrition.web_search import NutritionWebSearchService

PAGE = "https://example.test/synthetic-bar"
NOW = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


def response(
    values: list[dict[str, Any]], cited=(PAGE,), ref=1, read=(), narrated=False
) -> dict[str, Any]:
    """A Responses API result: the pages read, then the JSON text with citations."""
    narration = [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Ich suche die Werte ..."}],
        }
    ]
    return {
        "output": [
            *(narration if narrated else []),
            {
                "type": "web_search_call",
                "id": "ws_1",
                "action": {"sources": [{"url": url} for url in read]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"products": [{"ref": ref, "values": values}]}
                        ),
                        "annotations": [
                            {"type": "url_citation", "url": url} for url in cited
                        ],
                    }
                ],
            },
        ]
    }


def value(field: str, number: Any, url: str = PAGE) -> dict[str, Any]:
    return {"field": field, "value": number, "source_url": url}


def service(result: Any) -> tuple[NutritionWebSearchService, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append({"path": path, **payload})
        if isinstance(result, Exception):
            raise result
        return result

    return (
        NutritionWebSearchService(
            selected_model=lambda: "synthetic-model", openai_request=request
        ),
        sent,
    )


ROW = {
    "id": "own-1",
    "origin": "own",
    "name": "Synthetic bar",
    "brand": "Synthetic brand",
    "barcode": "4006381333931",
    "basis_amount": 100,
    "basis_unit": "g",
    "missing_fields": ["salt_g", "fiber_g"],
}


class NutritionWebSearchTests(unittest.TestCase):
    def test_request_carries_only_product_data(self) -> None:
        searcher, sent = service(response([]))
        searcher.search([ROW])
        request = sent[0]
        self.assertEqual(request["path"], "/v1/responses")
        self.assertEqual(request["model"], "synthetic-model")
        self.assertEqual(request["tools"], [{"type": "web_search"}])
        self.assertEqual(
            set(request),
            {
                "path",
                "model",
                "tools",
                "instructions",
                "input",
                "text",
                "store",
                "include",
                "reasoning",
                "service_tier",
            },
        )
        self.assertEqual(request["include"], ["web_search_call.action.sources"])
        # An auxiliary lookup never inherits a premium tier or high reasoning.
        self.assertEqual(
            (request["reasoning"], request["service_tier"]),
            ({"effort": "low"}, "default"),
        )
        self.assertEqual(
            json.loads(request["input"]),
            {
                "products": [
                    {
                        "ref": 1,
                        "name": "Synthetic bar",
                        "brand": "Synthetic brand",
                        "barcode": "4006381333931",
                        "basis_amount": 100,
                        "basis_unit": "g",
                        "missing_fields": ["salt_g", "fiber_g"],
                    }
                ]
            },
        )
        self.assertIn("untrusted", request["instructions"])
        self.assertEqual(request["text"]["format"]["type"], "json_schema")

    def test_values_are_kept_only_when_cited_plausible_and_missing(self) -> None:
        cases = {
            "cited": ([value("salt_g", 0.7)], (PAGE,), 1, 0),
            "cited with tracking parameter": (
                [value("salt_g", 0.7)],
                (PAGE + "/?utm_source=openai",),
                1,
                0,
            ),
            "uncited page": ([value("salt_g", 0.7)], ("https://other.test/",), 0, 1),
            "cited as http and www": (
                [value("salt_g", 0.7)],
                ("http://www.example.test/synthetic-bar",),
                1,
                0,
            ),
            "above the basis": ([value("fiber_g", 101)], (PAGE,), 0, 1),
            "not http": ([value("salt_g", 0.7, "ftp://example.test/x")], (), 0, 1),
            "known field": ([value("kcal", 400)], (PAGE,), 0, 1),
            "not a core field": ([value("sodium_g", 1)], (PAGE,), 0, 1),
            "negative": ([value("salt_g", -1)], (PAGE,), 0, 1),
            "above gram limit": ([value("fiber_g", 1001)], (PAGE,), 0, 1),
            "bool": ([value("salt_g", True)], (PAGE,), 0, 1),
            "text": ([value("salt_g", "0.7")], (PAGE,), 0, 1),
            "NaN": ([value("salt_g", float("nan"))], (PAGE,), 0, 1),
            "infinite": ([value("salt_g", float("inf"))], (PAGE,), 0, 1),
        }
        for label, (values, cited, kept, dropped) in cases.items():
            with self.subTest(label):
                result = service(response(values, cited))[0].search([ROW])
                self._assert_kept(result, kept, dropped)

    def test_a_page_the_search_read_counts_without_an_inline_citation(self) -> None:
        # JSON output carries no inline citations; the read sources still count,
        # and a narrating message before the answer is not part of the JSON.
        result = service(
            response([value("salt_g", 0.7)], cited=(), read=(PAGE,), narrated=True)
        )[0].search([ROW])
        self._assert_kept(result, 1, 0)

    def _assert_kept(self, result: dict[str, Any], kept: int, dropped: int) -> None:
        product = result["products"][0]
        self.assertEqual(len(product["values"]), kept)
        self.assertEqual(product["dropped"], dropped)
        self.assertEqual(result["data_origin"], "web")
        self.assertIn("untrusted", result["notice"])

    def test_kept_value_names_field_number_and_source_page(self) -> None:
        result = service(response([value("salt_g", 0.7), value("fiber_g", 2.5)]))[
            0
        ].search([ROW])
        self.assertEqual(
            result["products"],
            [
                {
                    "id": "own-1",
                    "name": "Synthetic bar",
                    "values": [value("salt_g", 0.7), value("fiber_g", 2.5)],
                    "dropped": 0,
                }
            ],
        )

    def test_an_unhashable_or_unknown_ref_is_dropped_without_failing(self) -> None:
        answer = response([value("salt_g", 0.7)])
        text = answer["output"][-1]["content"][0]
        found = json.loads(text["text"])["products"]
        text["text"] = json.dumps(
            {"products": [{"ref": [1], "values": []}, {"ref": "1"}, *found]}
        )
        result = service(answer)[0].search([ROW])
        self._assert_kept(result, 1, 0)

    def test_failures_give_unavailable_without_provider_text(self) -> None:
        cases = {
            "endpoint rejects the tool": AppError(
                400, "raw provider detail: tool web_search unsupported"
            ),
            "provider failure": AppError(502, "raw provider detail", reason="upstream"),
            "invalid JSON": {"output_text": "not json"},
            "wrong shape": {"output_text": json.dumps({"products": "x"})},
            "no output": {},
        }
        for label, result in cases.items():
            with self.subTest(label):
                outcome = service(result)[0].search([ROW])
                self.assertTrue(outcome["ok"])
                self.assertEqual(outcome["status"], "unavailable")
                self.assertIn("Websuche nicht verfügbar", outcome["notice"])
                self.assertNotIn("raw provider", json.dumps(outcome))

    def test_missing_model_or_transport_is_unavailable(self) -> None:
        for searcher in (
            NutritionWebSearchService(),
            NutritionWebSearchService(selected_model=lambda: "model"),
            NutritionWebSearchService(
                selected_model=lambda: "", openai_request=lambda *_: {}
            ),
        ):
            self.assertEqual(searcher.search([ROW])["status"], "unavailable")


class NutritionWebSearchCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager = temp_database(
            self,
            path=Path(temporary.name) / "web-search.db",
            row_factory=sqlite3.Row,
            schema=True,
        )
        self.searcher, self.sent = service(response([value("salt_g", 0.7)]))
        _, library = build_nutrition_services(
            manager,
            threading.Lock(),
            lambda: NOW.isoformat(),
            lambda: NOW,
            web_search=self.searcher,
        )
        self.catalog = library.product_catalog
        self.own = self.catalog.save_product(
            {
                "name": "Synthetic bar",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 400,
                "source": "manual",
            }
        )

    def test_only_incomplete_active_products_are_searched(self) -> None:
        complete = self.catalog.save_product(
            {
                **{key: 1 for key in ("kcal", "carbs_g", "protein_g", "fat_g")},
                "sugar_g": 1,
                "fiber_g": 1,
                "salt_g": 1,
                "name": "Synthetic complete",
                "basis_amount": 100,
                "basis_unit": "g",
                "source": "manual",
            }
        )
        archived = self.catalog.save_product(
            {"name": "Synthetic old", "basis_amount": 1, "basis_unit": "portion"}
        )
        self.catalog.archive_product(archived["id"])
        result = self.catalog.search_web_values(
            [self.own["id"], complete["id"], archived["id"], "unknown", self.own["id"]]
        )
        self.assertEqual([item["id"] for item in result["products"]], [self.own["id"]])
        self.assertEqual(result["skipped"], [complete["id"], archived["id"], "unknown"])
        self.assertEqual(len(self.sent), 1)
        sent_products = json.loads(self.sent[0]["input"])["products"]
        self.assertEqual(
            sent_products[0]["missing_fields"],
            ["carbs_g", "protein_g", "fat_g", "sugar_g", "fiber_g", "salt_g"],
        )

    def test_invalid_product_lists_are_rejected(self) -> None:
        for ids in (None, [], "x", [1], [" "], [str(n) for n in range(6)]):
            with self.subTest(ids=ids), self.assertRaises(AppError) as raised:
                self.catalog.search_web_values(ids)
            self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.sent, [])
        # Repeats and spaces count once: six entries of one product are one search.
        self.catalog.search_web_values([f" {self.own['id']} "] * 6)
        self.assertEqual(len(json.loads(self.sent[0]["input"])["products"]), 1)


if __name__ == "__main__":
    unittest.main()
