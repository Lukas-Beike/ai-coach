from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NutritionFrontendContractTests(unittest.TestCase):
    def test_camera_processing_is_bounded_and_rejects_before_state_mutation(self):
        nutrition = (ROOT / "public" / "nutrition.js").read_text(encoding="utf-8")
        app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function prepareNutritionImage(file", nutrition)
        self.assertIn("MAX_NUTRITION_IMAGE_EDGE = 1600", nutrition)
        self.assertIn("MAX_NUTRITION_IMAGE_BYTES = 1_200_000", nutrition)
        self.assertIn("createImageBitmap", nutrition)
        self.assertIn(
            'normalizedMime = String(file.type || "").toLowerCase() === "image/jpg" ? "image/jpeg"',
            nutrition,
        )
        self.assertIn("nutritionImageDataUrl(file, normalizedMime)", nutrition)
        self.assertIn("#nutritionLabelInput", nutrition)
        self.assertIn("#nutritionExtraction", nutrition)
        self.assertIn("#nutritionBarcodeDialog", nutrition)
        self.assertIn("#nutritionBarcodeVideo", nutrition)
        self.assertIn("#nutritionBarcodeManual", nutrition)
        self.assertIn("catch", nutrition)

        # The generic attachment handler must finish image preparation before
        # replacing state.chatAttachments, otherwise a Chromium decode failure
        # can discard the draft or leave a half-attached image. Image files go
        # through the shared helper, which owns the nutrition image processing.
        helper = app[
            app.index("async function prepareChatAttachment(file)") : app.index(
                '$("#attachmentInput").addEventListener'
            )
        ]
        handler = app[app.index('$("#attachmentInput").addEventListener') :]
        self.assertIn("prepareNutritionImage(file)", helper)
        self.assertIn("prepareChatAttachment", handler)
        self.assertIn("state.chatAttachments =", handler)
        self.assertLess(
            handler.index("await Promise.all(files.map(prepareChatAttachment))"),
            handler.index("state.chatAttachments ="),
        )
        self.assertIn("state.chatAttachmentsLoading = false", handler)
        self.assertIn("catch (error) { toast(error.message, true); }", handler)

        draft = nutrition[
            nutrition.index(
                "async function createNutritionProductDraft()"
            ) : nutrition.index("async function loadNutritionProducts(")
        ]
        self.assertIn("Produkt-ID: ${product.id}", draft)
        self.assertNotIn("product.name ||", draft)

    def test_nutrition_product_and_label_controls_are_exposed(self):
        index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        for selector in (
            'id="nutritionProductManual"',
            'id="nutritionLabelButton"',
            'id="nutritionLabelInput"',
            'id="nutritionProducts"',
            'id="nutritionExtraction"',
            'id="nutritionBarcodeDialog"',
            'id="nutritionBarcodeVideo"',
            'id="nutritionBarcodeManual"',
        ):
            self.assertIn(selector, index)

    def test_camera_and_product_assets_are_versioned_in_pwa_cache(self):
        index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        service_worker = (ROOT / "public" / "service-worker.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("/nutrition.js?v=", index)
        self.assertIn("/nutrition.js?v=", service_worker)
        self.assertIn("/app.js?v=", index)
        self.assertIn("/app.js?v=", service_worker)

    def test_composite_meal_details_keep_snapshots_safe_and_unknowns_visible(self):
        nutrition = (ROOT / "public" / "nutrition.js").read_text(encoding="utf-8")
        details = nutrition[
            nutrition.index("function nutritionComponentDetails(") : nutrition.index(
                "function nutritionCard("
            )
        ]
        self.assertIn('item.nutrition_basis?.kind === "composite"', details)
        self.assertIn("component.nutrition_basis", details)
        self.assertIn("name.textContent = component.name", details)
        self.assertIn("nutritionComponentSource(component.nutrition_basis)", details)
        self.assertIn('if (value == null || value === "") return "–";', nutrition)
        self.assertIn(
            'basis?.kind === "composite") return "Zusammengesetztes Essen', nutrition
        )
        self.assertNotIn("innerHTML", details)

    def test_barcode_camera_stops_tracks_on_close_and_start_failure(self):
        nutrition = (ROOT / "public" / "nutrition.js").read_text(encoding="utf-8")
        cleanup = nutrition[
            nutrition.index("function stopNutritionBarcode()") : nutrition.index(
                "async function scanNutritionBarcode()"
            )
        ]
        self.assertIn("getTracks().forEach((track) => track.stop())", cleanup)
        self.assertIn('addEventListener("close", stopNutritionBarcode)', nutrition)
        scanner = nutrition[
            nutrition.index("async function scanNutritionBarcode()") : nutrition.index(
                'document.querySelector("#nutritionProductSearch")'
            )
        ]
        self.assertIn("stopNutritionBarcode();", scanner)


if __name__ == "__main__":
    unittest.main()
