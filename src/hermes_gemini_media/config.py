# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Read non-secret settings (``image_gen.gemini.*`` / ``video_gen.gemini.*``) and resolve the model.

Model precedence (the agent never chooses a model; only the user does):
    explicit ``model`` argument from Hermes -> ``GEMINI_{IMAGE,VIDEO}_MODEL`` env
    -> ``<kind>_gen.gemini.model`` -> ``<kind>_gen.model`` (only if it is one of our ids)
    -> catalog default.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

from .constants import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    IMAGE_MODEL_ENV,
    PROVIDER_NAME,
    VIDEO_MODEL_ENV,
)

logger = logging.getLogger(__name__)

_KIND = {
    "image": ("image_gen", IMAGE_MODEL_ENV, DEFAULT_IMAGE_MODEL),
    "video": ("video_gen", VIDEO_MODEL_ENV, DEFAULT_VIDEO_MODEL),
}


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly()
        return cfg if isinstance(cfg, dict) else {}
    except Exception as exc:  # outside Hermes, or config unreadable
        logger.debug("config unavailable: %s", type(exc).__name__)
        return {}


def provider_settings(kind: str) -> dict[str, Any]:
    """``<kind>_gen.gemini`` mapping, ``{}`` when absent."""
    section = _load_config().get(_KIND[kind][0])
    if not isinstance(section, dict):
        return {}
    sub = section.get(PROVIDER_NAME)
    return sub if isinstance(sub, dict) else {}


def _str(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def strip_prefix(model_id: str) -> str:
    return model_id[len("models/"):] if model_id.startswith("models/") else model_id


def resolve_model(kind: str, caller_model: Optional[str], ordered_ids: Iterable[str]) -> str:
    """Pick the model id to use. ``ordered_ids`` is the catalog for ``kind``, best first."""
    section_key, env_name, default = _KIND[kind]
    ids = [strip_prefix(i) for i in ordered_ids]

    # An explicit choice is trusted even when unlisted (preview access differs per key).
    for candidate in (_str(caller_model), _str(os.environ.get(env_name)), _str(provider_settings(kind).get("model"))):
        if candidate:
            return strip_prefix(candidate)

    section = _load_config().get(section_key)
    shared = _str(section.get("model")) if isinstance(section, dict) else None
    if shared and strip_prefix(shared) in ids:  # image_gen.model is shared with other providers
        return strip_prefix(shared)

    if not ids or default in ids:
        return default
    return ids[0]
