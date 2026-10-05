"""Transient packaging-photo extraction through the selected model provider."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.providers import gemini as gemini_provider
from backend.providers import openai as openai_provider

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$")
INVALID_BASIS_AMOUNT = "Ungültige Bezugsmenge."


def validate_packaging_extraction(
    payload: Any, *, require_name: bool = True
) -> dict[str, Any]:
    """Validate a provider candidate without retaining the source image."""
    if not isinstance(payload, dict):
        raise AppError(
            400,
            "Die erkannte Nährwerttabelle ist ungültig.",
            reason="invalid_food_extraction",
        )
    name = str(payload.get("name") or "").strip()
    if (require_name and not name) or len(name) > 200:
        raise AppError(
            400, "Ein Produktname ist erforderlich.", reason="invalid_food_extraction"
        )
    basis_unit = str(payload.get("basis_unit") or "").strip().lower()
    if basis_unit and basis_unit not in {"g", "ml", "portion"}:
        raise AppError(400, INVALID_BASIS_AMOUNT, reason="invalid_food_extraction")
    basis_amount = None
    if payload.get("basis_amount") not in (None, ""):
        if isinstance(payload.get("basis_amount"), bool):
            raise AppError(400, INVALID_BASIS_AMOUNT, reason="invalid_food_extraction")
        try:
            basis_amount = float(payload.get("basis_amount"))  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise AppError(
                400, INVALID_BASIS_AMOUNT, reason="invalid_food_extraction"
            ) from exc
        if not math.isfinite(basis_amount) or not 0 < basis_amount <= 10000:
            raise AppError(
                400,
                "Bezugsmenge muss zwischen 0 und 10000 liegen.",
                reason="invalid_food_extraction",
            )
    result: dict[str, Any] = {
        "name": name,
        "brand": str(payload.get("brand") or "").strip()[:120],
        "barcode": _barcode(payload.get("barcode")),
        "basis_amount": basis_amount,
        "basis_unit": basis_unit or None,
        "source": "packaging_label",
    }
    for key in (
        "kcal",
        "carbs_g",
        "protein_g",
        "fat_g",
        "sugar_g",
        "fiber_g",
        "salt_g",
    ):
        value = payload.get(key)
        if value in (None, ""):
            result[key] = None
            continue
        if isinstance(value, bool):
            raise AppError(
                400, f"Ungültiger Wert für {key}.", reason="invalid_food_extraction"
            )
        try:
            number = float(str(value).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise AppError(
                400, f"Ungültiger Wert für {key}.", reason="invalid_food_extraction"
            ) from exc
        if not math.isfinite(number) or number < 0 or number > 10000:
            raise AppError(
                400, f"Ungültiger Wert für {key}.", reason="invalid_food_extraction"
            )
        result[key] = round(number, 1)
    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            confidence_value = float(confidence)
            result["confidence"] = (
                max(0.0, min(1.0, confidence_value))
                if math.isfinite(confidence_value)
                else None
            )
        except (TypeError, ValueError):
            result["confidence"] = None
    return {
        "ok": True,
        "candidate": result,
        "provenance": "packaging_label",
        "requires_confirmation": True,
    }


def _barcode(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = re.sub(r"\D", "", str(value))
    if len(text) not in {8, 12, 13, 14}:
        return None
    return text


def _image_data(data_url: Any) -> tuple[str, bytes]:
    if not isinstance(data_url, str) or len(data_url) > MAX_IMAGE_BYTES * 2:
        raise AppError(
            413, "Das Verpackungsfoto ist zu groß.", reason="food_image_too_large"
        )
    match = _DATA_URL.fullmatch(data_url)
    if not match:
        raise AppError(
            415,
            "Nur JPEG-, PNG- oder WebP-Fotos werden unterstützt.",
            reason="food_image_type",
        )
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AppError(
            400, "Das Verpackungsfoto ist ungültig.", reason="invalid_food_image"
        ) from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise AppError(
            413, "Das Verpackungsfoto ist zu groß.", reason="food_image_too_large"
        )
    signature_valid = (
        (match.group(1) == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (match.group(1) == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (
            match.group(1) == "image/webp"
            and len(data) >= 12
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
        )
    )
    if not signature_valid:
        raise AppError(
            415,
            "Dateityp und Bildinhalt stimmen nicht überein.",
            reason="food_image_type",
        )
    return match.group(1), data


class NutritionPhotoExtractionService:
    """Call OpenAI or Gemini once and retain only the validated candidate."""

    def __init__(
        self,
        *,
        selected_provider: Callable[[], str],
        selected_model: Callable[[str], str],
        openai_request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        openai_path: str = "/v1/responses",
        gemini_generate: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._selected_provider = selected_provider
        self._selected_model = selected_model
        self._openai_request = openai_request
        self._openai_path = openai_path
        self._gemini_generate = gemini_generate

    def extract(self, data_url: Any) -> dict[str, Any]:
        mime, image = _image_data(data_url)
        provider = str(self._selected_provider() or "openai").casefold()
        model = self._selected_model(provider)
        instruction = (
            "Lies die deutsche Nährwerttabelle dieses Produktfotos. Antworte ausschließlich als JSON "
            "mit name, brand, barcode, basis_amount, basis_unit, kcal, carbs_g, protein_g, fat_g, "
            "sugar_g, fiber_g, salt_g und confidence. Unlesbare Werte sowie unbekannte basis_amount/basis_unit sind null; nicht raten. basis_unit ist g, ml oder portion. Der Produktname darf fehlen, wenn nur eine Nährwerttabelle sichtbar ist."
        )
        encoded = base64.b64encode(image).decode("ascii")
        if provider == "gemini":
            if self._gemini_generate is None:
                raise AppError(
                    503,
                    "Der gewählte KI-Anbieter ist nicht verfügbar.",
                    reason="provider_unavailable",
                )
            response = self._gemini_generate(
                model,
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"inlineData": {"mimeType": mime, "data": encoded}},
                                {"text": instruction},
                            ],
                        }
                    ],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
            )
            text = _gemini_text(response)
        else:
            if self._openai_request is None:
                raise AppError(
                    503,
                    "Der gewählte KI-Anbieter ist nicht verfügbar.",
                    reason="provider_unavailable",
                )
            response = self._openai_request(
                self._openai_path,
                {
                    "model": model,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": instruction},
                                {
                                    "type": "input_image",
                                    "image_url": f"data:{mime};base64,{encoded}",
                                },
                            ],
                        }
                    ],
                    "text": {"format": {"type": "json_object"}},
                },
            )
            text = _openai_text(response)
        try:
            candidate = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise AppError(
                502,
                "Die Nährwerttabelle konnte nicht gelesen werden.",
                reason="invalid_provider_response",
            ) from exc
        return validate_packaging_extraction(candidate, require_name=False)


def _openai_text(response: Any) -> str:
    return openai_provider.response_text(response) if isinstance(response, dict) else ""


def _gemini_text(response: Any) -> str:
    return gemini_provider.response_text(response)
