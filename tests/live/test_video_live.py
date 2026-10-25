# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
"""Real video generation at 360p / 3 s (smallest, cheapest). Run:  pytest -m live tests/live/test_video_live.py -s"""

import base64
import os
from pathlib import Path

import pytest

from hermes_gemini_media import media_io
from hermes_gemini_media.image_provider import GeminiImageGenProvider
from hermes_gemini_media.video_provider import GeminiVideoGenProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
]


def _check(out, expected_task):
    if not out["success"] and out.get("error_type") == "timeout":
        # The Omni service stalls intermittently (seen 3 of 4 calls at one point); not a plugin bug.
        pytest.skip(f"Gemini video service did not respond in time: {out['error']}")
    assert out["success"], out
    path = Path(out["video"])
    raw = path.read_bytes()
    assert raw[4:8] == b"ftyp" and len(raw) > 20_000
    assert out["task"] == expected_task and out["resolution"] == "360p"
    seconds = media_io.mp4_duration_seconds(raw)
    assert seconds is not None and 2.5 <= seconds <= 3.5, seconds
    print(expected_task, "->", path, f"{seconds}s", f"{len(raw) // 1024}KB")


def test_text_then_image_to_video():
    video = GeminiVideoGenProvider()
    _check(video.generate("A red apple slowly rolling across a white table", duration=3, resolution="360p"),
           "text_to_video")

    still = GeminiImageGenProvider().generate("A flat illustration of a single red apple on a white table", "landscape")
    assert still["success"], still
    _check(video.generate("The apple rolls gently to the right", image_url=still["image"], duration=3,
                          resolution="360p"), "image_to_video")


def test_reference_to_video_with_two_images(tmp_path):
    images = GeminiImageGenProvider()
    a = images.generate("A cartoon orange cat sitting, plain background", "square")
    b = images.generate("A ball of blue yarn, plain background", "square")
    assert a["success"] and b["success"]
    out = GeminiVideoGenProvider().generate(
        "The cat plays with the ball of yarn", reference_image_urls=[a["image"], b["image"]],
        duration=3, resolution="360p")
    _check(out, "reference_to_video")
