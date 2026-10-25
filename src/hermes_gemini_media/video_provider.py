# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
"""``video_generate`` backend: Gemini Omni through the Interactions API.

The call is synchronous and returns the MP4 inline (base64); there is no operation to poll.
Routing, measured against the live API:

* no media                       -> ``text_to_video``
* ``image_url`` only             -> ``image_to_video`` (the image is the first frame)
* ``reference_image_urls`` (with or without ``image_url``) -> ``reference_to_video``
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from agent.image_gen_provider import normalize_reference_images
from agent.video_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    VideoGenProvider,
    error_response,
    save_b64_video,
    success_response,
)

from . import config, errors, media_io, models
from .auth import AuthStrategy, default_auth
from .client import build_client, call_with_deadline, sdk_available
from .constants import API_KEY_ENV_VARS, API_KEY_URL, PROVIDER_NAME, VIDEO_REQUEST_TIMEOUT_S

logger = logging.getLogger(__name__)

_BLOCK_WORDS = ("safety", "blocked", "prohibited", "policy", "cannot", "can't", "unable", "refus")


def normalize_aspect(value: Any) -> tuple[str, bool]:
    """Map any requested aspect to ``16:9`` or ``9:16``. Returns ``(aspect, was_changed)``."""
    text = str(value or "").strip().lower()
    if text in models.VIDEO_ASPECT_RATIOS:
        return text, False
    if text == "portrait":
        return "9:16", True
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)", text)
    if match and float(match.group(2)) > float(match.group(1)):
        return "9:16", True
    return "16:9", bool(text) and text != "landscape"


def normalize_resolution(value: Any) -> tuple[str, bool]:
    """Round a requested resolution up to a supported one. Returns ``(resolution, was_changed)``."""
    text = str(value or "").strip().lower()
    if text in models.VIDEO_RESOLUTIONS:
        return text, False
    if text in ("2k", "uhd", "2160p"):
        return "4k", True
    digits = re.search(r"\d+", text)
    pixels = int(digits.group()) if digits else 720
    for label, limit in (("360p", 360), ("720p", 720), ("1080p", 1080)):
        if pixels <= limit:
            return label, True
    return "4k", True


def normalize_duration(value: Any) -> tuple[Optional[int], bool]:
    """Clamp to the 3-10 s window. ``None`` (unset) is left to the model's default."""
    if value in (None, "", 0):
        return None, False
    try:
        requested = float(value)
    except (TypeError, ValueError):
        return None, True
    clamped = max(models.VIDEO_MIN_DURATION, min(models.VIDEO_MAX_DURATION, int(round(requested))))
    return clamped, clamped != requested


class GeminiVideoGenProvider(VideoGenProvider):
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
            "env_vars": [{"key": API_KEY_ENV_VARS[0], "prompt": "Gemini API key", "url": API_KEY_URL}],
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": list(models.VIDEO_ASPECT_RATIOS),
            "resolutions": list(models.VIDEO_RESOLUTIONS),
            "min_duration": models.VIDEO_MIN_DURATION,
            "max_duration": models.VIDEO_MAX_DURATION,
            "supports_audio": True,
            "audio_always_on": True,
            "supports_negative_prompt": False,
            "supports_seed": False,
            "supports_upscale": False,
            "max_reference_images": models.VIDEO_MAX_REFS,
        }

    # -- generation ----------------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = "720p",
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = prompt.strip() if isinstance(prompt, str) else ""
        aspect, aspect_changed = normalize_aspect(aspect_ratio)

        def fail(message: str, error_type: str, model_id: str = "") -> dict[str, Any]:
            return error_response(
                error=errors.redact(message), error_type=error_type, provider=self.name,
                model=model_id, prompt=prompt, aspect_ratio=aspect,
            )

        if not prompt:
            return fail("Prompt is required and must be a non-empty string", errors.INVALID_REQUEST)
        if not sdk_available():
            return fail("The google-genai package is not installed. Run `hermes pm repair`, then restart Hermes.",
                        errors.MISSING_DEPENDENCY)
        if not self._auth.is_configured():
            return fail(self._auth.missing_message(), errors.MISSING_CREDENTIALS)

        model_id = config.resolve_model(models.VIDEO, model, [m.id for m in self._catalog()])
        res, res_changed = normalize_resolution(resolution)
        seconds, duration_changed = normalize_duration(duration)

        primary = image_url.strip() if isinstance(image_url, str) and image_url.strip() else None
        references = normalize_reference_images(reference_image_urls) or []
        sources = ([primary] if primary else []) + references
        dropped = max(0, len(sources) - models.VIDEO_MAX_REFS)
        sources = sources[: models.VIDEO_MAX_REFS]
        try:
            images = media_io.load_references(sources)
        except media_io.ReferenceImageError as exc:
            return fail(str(exc), errors.INVALID_REQUEST, model_id)
        except Exception as exc:  # e.g. Hermes's credential-file read guard
            return fail(f"Could not read a reference image: {exc}", errors.INVALID_REQUEST, model_id)

        if not images:
            task = "text_to_video"
        elif len(images) == 1 and primary:
            task = "image_to_video"
        else:
            task = "reference_to_video"

        response_format: dict[str, Any] = {"type": "video", "aspect_ratio": aspect, "resolution": res}
        if seconds is not None:
            response_format["duration"] = f"{seconds}s"  # the API rejects a bare number
        contents: Any = (
            [{"type": "image", "data": i.b64, "mime_type": i.mime_type} for i in images]
            + [{"type": "text", "text": prompt}]
        ) if images else prompt

        try:
            deadline = config.timeout_seconds("video", VIDEO_REQUEST_TIMEOUT_S)
            client = self._client_factory(self._auth, timeout_s=deadline)
            request: dict[str, Any] = {"model": model_id, "input": contents, "response_format": response_format}
            if images:
                # Never send task=text_to_video: measured live, that explicit task hangs until the
                # client timeout, while omitting generation_config for text prompts returns in ~20 s.
                request["generation_config"] = {"video_config": {"task": task}}
            interaction = call_with_deadline(lambda: client.interactions.create(**request), deadline)
        except Exception as exc:
            error_type, message = errors.classify_exception(exc)
            logger.debug("video generation failed: %s", error_type)
            return fail(message, error_type, model_id)

        output = getattr(interaction, "output_video", None)
        data = getattr(output, "data", None)
        if not data:
            text = (getattr(interaction, "output_text", "") or "").strip()
            status = getattr(interaction, "status", "") or ""
            blocked = any(w in text.lower() for w in _BLOCK_WORDS) or status in ("failed", "cancelled")
            detail = text or f"The model returned no video (status: {status or 'unknown'})."
            return fail(detail, errors.CONTENT_BLOCKED if blocked else errors.PROVIDER_ERROR, model_id)

        try:
            path = save_b64_video(data, prefix="gemini", extension="mp4")
        except Exception as exc:
            return fail(f"Could not save the generated video: {exc}", errors.PROVIDER_ERROR, model_id)

        actual = media_io.mp4_duration_seconds(path.read_bytes()) if path.stat().st_size < 64 * 1024 * 1024 else None
        extra: dict[str, Any] = {
            "mime_type": getattr(output, "mime_type", None) or "video/mp4",
            "resolution": res,
            "task": task,
            "audio": "native",  # always generated; cannot be switched off
            "references_used": len(images),
        }
        if aspect_changed:
            extra["aspect_ratio_adjusted"] = True
        if res_changed:
            extra["resolution_adjusted"] = True
        if duration_changed:
            extra["duration_adjusted"] = True
        if dropped:
            extra["references_dropped"] = dropped
        ignored = [n for n, v in (("negative_prompt", negative_prompt), ("seed", seed)) if v not in (None, "")]
        if audio is False:
            ignored.append("audio=false")
        if ignored:
            extra["ignored_parameters"] = ignored
        if getattr(interaction, "id", None):
            extra["interaction_id"] = interaction.id
        return success_response(
            video=str(path), model=model_id, prompt=prompt, modality="image" if images else "text",
            aspect_ratio=aspect, duration=int(round(actual)) if actual else (seconds or 0),
            provider=self.name, extra=extra,
        )
