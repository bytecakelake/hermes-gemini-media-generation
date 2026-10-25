# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""``image_generate`` backend: Gemini image models ("Nano Banana") through the Interactions API.

One call covers text-to-image and reference-guided generation/editing: ``image_url`` and
``reference_image_urls`` are sent as inline image parts before the prompt.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)

from . import config, errors, media_io, models
from .auth import AuthStrategy, default_auth
from .client import build_client, sdk_available
from .constants import API_KEY_ENV_VARS, API_KEY_URL, IMAGE_REQUEST_TIMEOUT_S, PROVIDER_NAME

logger = logging.getLogger(__name__)

# Hermes exposes three semantic aspects; Gemini takes explicit ratios.
GEMINI_ASPECT = {"landscape": "16:9", "square": "1:1", "portrait": "9:16"}
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_BLOCK_WORDS = ("safety", "blocked", "prohibited", "policy", "cannot", "can't", "unable", "refus")


def _clamp_size(requested: Optional[str], allowed: Optional[tuple[str, ...]]) -> tuple[Optional[str], bool]:
    """Return ``(size, was_changed)``. Unknown model (``allowed`` None) passes the value through."""
    if not isinstance(requested, str) or not requested.strip():
        return None, False
    requested = requested.strip().upper()
    if allowed is None or requested in allowed:
        return requested, False
    return allowed[0], True  # the smallest supported size is the safe fallback


class GeminiImageGenProvider(ImageGenProvider):
    def __init__(
        self,
        auth: Optional[AuthStrategy] = None,
        client_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._auth = auth or default_auth()
        self._client_factory = client_factory or build_client

    # -- identity / picker ---------------------------------------------------------------------
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
            "env_vars": [{"key": API_KEY_ENV_VARS[0], "prompt": "Gemini API key", "url": API_KEY_URL}],
        }

    def capabilities(self) -> dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": models.DEFAULT_IMAGE_MAX_REFS}

    # -- generation ----------------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        aspect = resolve_aspect_ratio(aspect_ratio)
        prompt = prompt.strip() if isinstance(prompt, str) else ""

        def fail(message: str, error_type: str, model: str = "") -> dict[str, Any]:
            return error_response(
                error=errors.redact(message), error_type=error_type, provider=self.name,
                model=model, prompt=prompt, aspect_ratio=aspect,
            )

        if not prompt:
            return fail("Prompt is required and must be a non-empty string", errors.INVALID_REQUEST)
        if not sdk_available():
            return fail("The google-genai package is not installed. Run `hermes pm repair`, then restart Hermes.",
                        errors.MISSING_DEPENDENCY)
        if not self._auth.is_configured():
            return fail(self._auth.missing_message(), errors.MISSING_CREDENTIALS)

        model = config.resolve_model(models.IMAGE, kwargs.get("model"), [m.id for m in self._catalog()])
        limits = models.image_limits(model)

        # reference images: primary image_url first, then references, clamped to the model limit
        sources: list[str] = []
        if isinstance(image_url, str) and image_url.strip():
            sources.append(image_url.strip())
        sources.extend(normalize_reference_images(reference_image_urls) or [])
        dropped = max(0, len(sources) - limits["max_refs"])
        sources = sources[: limits["max_refs"]]
        try:
            references = media_io.load_references(sources)
        except media_io.ReferenceImageError as exc:
            return fail(str(exc), errors.INVALID_REQUEST, model)
        except Exception as exc:  # e.g. Hermes's credential-file read guard
            return fail(f"Could not read a reference image: {exc}", errors.INVALID_REQUEST, model)

        size, size_changed = _clamp_size(config.provider_settings("image").get("image_size"), limits["sizes"])
        response_format: dict[str, Any] = {"type": "image", "aspect_ratio": GEMINI_ASPECT[aspect]}
        if size:
            response_format["image_size"] = size

        if references:
            contents: Any = [
                {"type": "image", "data": r.b64, "mime_type": r.mime_type} for r in references
            ] + [{"type": "text", "text": prompt}]
        else:
            contents = prompt

        try:
            client = self._client_factory(self._auth, timeout_s=IMAGE_REQUEST_TIMEOUT_S)
            interaction = client.interactions.create(model=model, input=contents, response_format=response_format)
        except Exception as exc:
            error_type, message = errors.classify_exception(exc)
            logger.debug("image generation failed: %s", error_type)
            return fail(message, error_type, model)

        output = getattr(interaction, "output_image", None)
        data = getattr(output, "data", None)
        if not data:
            text = (getattr(interaction, "output_text", "") or "").strip()
            status = getattr(interaction, "status", "") or ""
            blocked = any(w in text.lower() for w in _BLOCK_WORDS) or status in ("failed", "cancelled")
            detail = text or f"The model returned no image (status: {status or 'unknown'})."
            return fail(detail, errors.CONTENT_BLOCKED if blocked else errors.PROVIDER_ERROR, model)

        mime = getattr(output, "mime_type", None) or "image/png"
        try:
            path = save_b64_image(data, prefix="gemini", extension=_EXTENSIONS.get(mime, "png"))
        except Exception as exc:
            return fail(f"Could not save the generated image: {exc}", errors.PROVIDER_ERROR, model)

        extra: dict[str, Any] = {
            "mime_type": mime,
            "gemini_aspect_ratio": GEMINI_ASPECT[aspect],
            "references_used": len(references),
        }
        if size:
            extra["image_size"] = size
        if size_changed:
            extra["image_size_adjusted"] = True
        if dropped:
            extra["references_dropped"] = dropped
        if getattr(interaction, "id", None):
            extra["interaction_id"] = interaction.id
        return success_response(
            image=str(path), model=model, prompt=prompt, aspect_ratio=aspect, provider=self.name,
            modality="image" if references else "text", extra=extra,
        )
