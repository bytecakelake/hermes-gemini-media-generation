# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Real image generation (small cost). Run with:  pytest -m live tests/live/test_image_live.py -s"""

import os
from pathlib import Path

import pytest

from hermes_gemini_media.image_provider import GeminiImageGenProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
]


def test_text_to_image_then_reference_edit():
    provider = GeminiImageGenProvider()
    first = provider.generate("A flat illustration of a single red apple on a white table", "square")
    assert first["success"], first
    path = Path(first["image"])
    assert path.is_file() and path.stat().st_size > 10_000
    print("text->image:", path, first["model"], first.get("mime_type"))

    edited = provider.generate("Make the apple green and keep everything else the same", "square", image_url=str(path))
    assert edited["success"], edited
    assert edited["modality"] == "image" and edited["references_used"] == 1
    print("reference edit:", edited["image"])
