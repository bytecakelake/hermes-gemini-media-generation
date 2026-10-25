# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""``image_generate`` backend (Gemini image models). Phase 1: discovery, setup and model catalog.
``generate`` lands in Phase 2."""

from __future__ import annotations

from typing import Any, Optional

from agent.image_gen_provider import DEFAULT_ASPECT_RATIO, ImageGenProvider, error_response

from . import config, errors, models
from .auth import AuthStrategy, default_auth
from .client import sdk_available
from .constants import API_KEY_ENV_VARS, API_KEY_URL, PROVIDER_NAME


class GeminiImageGenProvider(ImageGenProvider):
    def __init__(self, auth: Optional[AuthStrategy] = None) -> None:
        self._auth = auth or default_auth()

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Google Gemini (Nano Banana)"

    def is_available(self) -> bool:
        # No network: called on every picker paint.
        return sdk_available() and self._auth.is_configured()

    def _catalog(self) -> list[models.ModelInfo]:
        catalog, _source = models.get_catalog(self._auth)
        return models.models_of(models.IMAGE, catalog)

    def list_models(self) -> list[dict[str, Any]]:
        return [m.picker_row() for m in self._catalog()]

    def default_model(self) -> Optional[str]:
        return config.resolve_model(models.IMAGE, None, [m.id for m in self._catalog()])

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": self.display_name,
            "badge": "paid",
            "tag": "Gemini image models via the Gemini API (API key)",
            "env_vars": [
                {"key": API_KEY_ENV_VARS[0], "prompt": "Gemini API key", "url": API_KEY_URL},
            ],
        }

    def capabilities(self) -> dict[str, Any]:
        # Up to 14 reference images per request on the current Nano Banana models (per-model
        # sub-limits are applied in generate(), Phase 2).
        return {"modalities": ["text", "image"], "max_reference_images": 14}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return error_response(
            error="Gemini image generation is not implemented yet (Phase 2).",
            error_type=errors.PROVIDER_ERROR,
            provider=self.name,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
        )
