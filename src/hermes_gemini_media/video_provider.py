# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""``video_generate`` backend (Gemini Omni). Phase 1: discovery, setup and model catalog.
``generate`` lands in Phase 4."""

from __future__ import annotations

from typing import Any, Optional

from agent.video_gen_provider import VideoGenProvider, error_response

from . import config, errors, models
from .auth import AuthStrategy, default_auth
from .client import sdk_available
from .constants import API_KEY_ENV_VARS, API_KEY_URL, PROVIDER_NAME


class GeminiVideoGenProvider(VideoGenProvider):
    def __init__(self, auth: Optional[AuthStrategy] = None) -> None:
        self._auth = auth or default_auth()

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Google Gemini (Omni)"

    def is_available(self) -> bool:
        return sdk_available() and self._auth.is_configured()

    def _catalog(self) -> list[models.ModelInfo]:
        catalog, _source = models.get_catalog(self._auth)
        return models.models_of(models.VIDEO, catalog)

    def list_models(self) -> list[dict[str, Any]]:
        return [dict(m.picker_row(), modalities=["text", "image"]) for m in self._catalog()]

    def default_model(self) -> Optional[str]:
        return config.resolve_model(models.VIDEO, None, [m.id for m in self._catalog()])

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": self.display_name,
            "badge": "paid",
            "tag": "Gemini Omni video generation via the Gemini API (API key)",
            "env_vars": [
                {"key": API_KEY_ENV_VARS[0], "prompt": "Gemini API key", "url": API_KEY_URL},
            ],
        }

    def capabilities(self) -> dict[str, Any]:
        # Provisional until Phase 4 verifies limits live. Duration is not a Gemini Omni parameter.
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["360p", "720p", "1080p", "4k"],
            "supports_audio": True,
            "supports_negative_prompt": False,
            "supports_seed": False,
            "max_reference_images": 0,
        }

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return error_response(
            error="Gemini video generation is not implemented yet (Phase 4).",
            error_type=errors.PROVIDER_ERROR,
            provider=self.name,
            prompt=prompt,
            aspect_ratio=str(kwargs.get("aspect_ratio") or ""),
        )
