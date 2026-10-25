# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
"""Hermes entry point: registers both backends from one plugin."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    from .image_provider import GeminiImageGenProvider
    from .video_provider import GeminiVideoGenProvider

    ctx.register_image_gen_provider(GeminiImageGenProvider())
    ctx.register_video_gen_provider(GeminiVideoGenProvider())
