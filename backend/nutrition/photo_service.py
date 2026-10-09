"""Use case for nutrition label photo extraction."""

from __future__ import annotations

from typing import Any

from backend.errors import AppError
from backend.nutrition.photo import (
    NutritionPhotoExtractionService,
    validate_packaging_extraction,
)


class PhotoExtractionService:
    def __init__(self, extractor: NutritionPhotoExtractionService | None) -> None:
        self.extractor = extractor

    def extract_packaging_photo(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AppError(400, "Ungültiger Fotoinhalt.")
        if payload.get("image_data_url"):
            if not self.extractor:
                raise AppError(
                    503,
                    "Fotoerkennung ist nicht verfügbar.",
                    reason="provider_unavailable",
                )
            result = self.extractor.extract(payload["image_data_url"])
        else:
            result = validate_packaging_extraction(payload)
        return {**result, "extraction": result["candidate"]}
