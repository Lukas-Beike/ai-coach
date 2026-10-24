from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import Mock

from test_nutrition_api_and_sync import GLOBAL_BODY_BYTES, json_route_handler

from backend.errors import AppError
from backend.http_api.nutrition import NUTRITION_PRODUCTS_PATH, NutritionPostRoutes
from backend.nutrition.photo import (
    MAX_IMAGE_BYTES,
    PHOTO_REQUEST_MAX_BYTES,
    NutritionPhotoExtractionService,
)
from backend.nutrition.photo_service import PhotoExtractionService

EXTRACT_PATH = f"{NUTRITION_PRODUCTS_PATH}/extract"


class NutritionPhotoExtractionTests(unittest.TestCase):
    @staticmethod
    def data_url(image=b"\xff\xd8\xffsynthetic-image"):
        return "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")

    @staticmethod
    def candidate_json():
        return json.dumps(
            {
                "name": "Synthetic whey",
                "brand": "Example brand",
                "barcode": "4006381333931",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 376,
                "carbs_g": 8,
                "protein_g": 78,
                "fat_g": 5.5,
                "sugar_g": 4,
                "fiber_g": None,
                "salt_g": 0.4,
                "confidence": 0.94,
            }
        )

    def test_openai_request_uses_selected_model_transient_image_and_json_candidate(
        self,
    ):
        request = Mock(return_value={"output_text": self.candidate_json()})
        service = NutritionPhotoExtractionService(
            selected_model=lambda: "gpt-6-luna",
            openai_request=request,
        )

        result = service.extract(self.data_url())

        request.assert_called_once()
        path, payload = request.call_args.args
        self.assertEqual(path, "/v1/responses")
        self.assertEqual(payload["model"], "gpt-6-luna")
        image_input = payload["input"][0]["content"][1]
        self.assertEqual(image_input["type"], "input_image")
        self.assertTrue(image_input["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(result["provenance"], "packaging_label")
        self.assertTrue(result["requires_confirmation"])
        self.assertIsNone(result["candidate"]["fiber_g"])
        self.assertNotIn("image", result)
        self.assertNotIn("image_data_url", result)

    def test_invalid_provider_response_fails_without_returning_provider_text_or_image(
        self,
    ):
        service = NutritionPhotoExtractionService(
            selected_model=lambda: "gpt-6-luna",
            openai_request=lambda _path, _payload: {
                "output_text": "Synthetic secret provider response",
            },
        )

        with self.assertRaises(AppError) as raised:
            service.extract(self.data_url())

        self.assertEqual(raised.exception.reason, "invalid_provider_response")
        self.assertNotIn("Synthetic secret", str(raised.exception))

    def test_invalid_photo_and_missing_model_are_rejected_before_network(
        self,
    ):
        request = Mock()
        service = NutritionPhotoExtractionService(
            selected_model=lambda: "gpt-6-luna",
            openai_request=request,
        )
        for data_url in (
            "https://example.test/photo.jpg",
            "data:image/svg+xml;base64,AA==",
        ):
            with self.subTest(data_url=data_url), self.assertRaises(AppError):
                service.extract(data_url)
        request.assert_not_called()

        unavailable = NutritionPhotoExtractionService()
        with self.assertRaises(AppError) as raised:
            unavailable.extract(self.data_url())
        self.assertEqual(raised.exception.reason, "provider_unavailable")

    def test_grouped_thousands_become_unknown_while_other_fields_extract(self):
        for kcal in ("1,200", "1.200"):
            candidate = {
                **json.loads(self.candidate_json()),
                "kcal": kcal,
                "carbs_g": "1,200",
                "sugar_g": "1.200",
                "fat_g": "5,5",
            }
            service = NutritionPhotoExtractionService(
                selected_model=lambda: "gpt-6-luna",
                openai_request=Mock(
                    return_value={"output_text": json.dumps(candidate)}
                ),
            )
            with self.subTest(kcal=kcal):
                result = service.extract(self.data_url())["candidate"]
                self.assertIsNone(result["kcal"])
                self.assertIsNone(result["carbs_g"])
                self.assertEqual(
                    (result["sugar_g"], result["fat_g"], result["protein_g"]),
                    (1.2, 5.5, 78),
                )


class NutritionPhotoRouteBodyTests(unittest.TestCase):
    """The extract route reads photo bodies above the global JSON cap."""

    def setUp(self) -> None:
        self.request = Mock(
            return_value={"output_text": NutritionPhotoExtractionTests.candidate_json()}
        )
        extractor = NutritionPhotoExtractionService(
            selected_model=lambda: "gpt-6-luna", openai_request=self.request
        )
        library = Mock()
        library.extract_packaging_photo = PhotoExtractionService(
            extractor
        ).extract_packaging_photo
        self.routes = NutritionPostRoutes(Mock, lambda: library, sync_job_queue=Mock)

    def test_compressed_and_largest_valid_photos_are_extracted_once(self):
        for size in (1_200_000, MAX_IMAGE_BYTES):
            self.request.reset_mock()
            image = b"\xff\xd8\xff" + bytes(size - 3)
            handler = json_route_handler(
                {"image_data_url": NutritionPhotoExtractionTests.data_url(image)}
            )
            with self.subTest(size=size):
                self.assertGreater(
                    int(handler.headers["Content-Length"]), GLOBAL_BODY_BYTES
                )
                self.assertTrue(self.routes.handle(handler, EXTRACT_PATH))
                self.assertEqual(handler.send_json.call_args.args[0], 200)
                self.request.assert_called_once()

    def test_body_above_the_photo_cap_is_rejected_before_extraction(self):
        handler = json_route_handler(
            {"image_data_url": NutritionPhotoExtractionTests.data_url()},
            padding=PHOTO_REQUEST_MAX_BYTES,
        )

        with self.assertRaises(AppError) as raised:
            self.routes.handle(handler, EXTRACT_PATH)

        self.assertEqual(raised.exception.status, 413)
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
