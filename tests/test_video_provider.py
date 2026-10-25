# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
import base64
import struct
from types import SimpleNamespace as NS

import pytest

from hermes_gemini_media import config, media_io, models
from hermes_gemini_media.video_provider import (
    GeminiVideoGenProvider,
    normalize_aspect,
    normalize_duration,
    normalize_resolution,
)
from samples import LIVE_SAMPLE

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def fake_mp4(seconds=4, timescale=1000):
    mvhd = b"mvhd" + b"\x00" + b"\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, seconds * timescale)
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00" + mvhd + b"\x00" * 64


class FakeInteractions:
    def __init__(self, result, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.result


def ok_result(raw=None):
    raw = raw or fake_mp4()
    return NS(output_video=NS(data=base64.b64encode(raw).decode(), mime_type="video/mp4"),
              output_text="", status="completed", id="v1_vid")


def provider(fake_auth, result=None, exc=None, configured=True):
    inter = FakeInteractions(result if result is not None else ok_result(), exc)
    p = GeminiVideoGenProvider(fake_auth(configured=configured),
                               client_factory=lambda auth, timeout_s: NS(interactions=inter))
    return p, inter


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    cat = models.parse_sdk_models(LIVE_SAMPLE)
    monkeypatch.setattr(models, "get_catalog", lambda auth, **kw: (cat, "live"))
    monkeypatch.setattr(config, "_load_config", lambda: {})


def write(tmp_path, name, raw):
    path = tmp_path / name
    path.write_bytes(raw)
    return str(path)


# -- normalisers -------------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [
    ("16:9", ("16:9", False)), ("9:16", ("9:16", False)), ("landscape", ("16:9", False)),
    ("portrait", ("9:16", True)), ("1:1", ("16:9", True)), ("3:4", ("9:16", True)), ("21:9", ("16:9", True)),
])
def test_normalize_aspect(value, expected):
    assert normalize_aspect(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("360p", ("360p", False)), ("720p", ("720p", False)), ("1080p", ("1080p", False)), ("4k", ("4k", False)),
    ("480p", ("720p", True)), ("540p", ("720p", True)), ("240p", ("360p", True)), ("2160p", ("4k", True)),
])
def test_normalize_resolution(value, expected):
    assert normalize_resolution(value) == expected


@pytest.mark.parametrize("value, expected", [
    (None, (None, False)), (5, (5, False)), (2, (3, True)), (15, (10, True)), ("8", (8, False)), (7.6, (8, True)),
])
def test_normalize_duration(value, expected):
    assert normalize_duration(value) == expected


def test_mp4_duration_parser():
    assert media_io.mp4_duration_seconds(fake_mp4(7)) == 7.0
    assert media_io.mp4_duration_seconds(b"not an mp4") is None


# -- generate ----------------------------------------------------------------------------------
def test_text_to_video(fake_auth):
    p, inter = provider(fake_auth)
    out = p.generate("a rolling apple")
    assert out["success"] and out["video"].endswith(".mp4") and out["modality"] == "text"
    assert out["model"] == "gemini-omni-1.1-flash" and out["provider"] == "gemini"
    assert out["duration"] == 4 and out["task"] == "text_to_video" and out["audio"] == "native"
    call = inter.calls[0]
    assert call["input"] == "a rolling apple"
    assert call["response_format"] == {"type": "video", "aspect_ratio": "16:9", "resolution": "720p"}
    assert "generation_config" not in call  # explicit text_to_video hangs on the live API
    with open(out["video"], "rb") as fh:
        assert fh.read(12)[4:8] == b"ftyp"


def test_duration_is_sent_as_seconds_string_and_clamped(fake_auth):
    p, inter = provider(fake_auth)
    assert p.generate("x", duration=5)["success"]
    assert inter.calls[-1]["response_format"]["duration"] == "5s"
    out = p.generate("x", duration=30)
    assert inter.calls[-1]["response_format"]["duration"] == "10s" and out["duration_adjusted"] is True
    p.generate("x", duration=1)
    assert inter.calls[-1]["response_format"]["duration"] == "3s"
    p.generate("x")
    assert "duration" not in inter.calls[-1]["response_format"]


def test_aspect_and_resolution_are_normalised_and_reported(fake_auth):
    p, inter = provider(fake_auth)
    out = p.generate("x", aspect_ratio="1:1", resolution="480p")
    rf = inter.calls[0]["response_format"]
    assert rf["aspect_ratio"] == "16:9" and rf["resolution"] == "720p"
    assert out["aspect_ratio_adjusted"] and out["resolution_adjusted"] and out["aspect_ratio"] == "16:9"


def test_image_url_only_is_image_to_video(fake_auth, tmp_path):
    p, inter = provider(fake_auth)
    out = p.generate("animate", image_url=write(tmp_path, "a.png", PNG))
    assert out["modality"] == "image" and out["task"] == "image_to_video" and out["references_used"] == 1
    parts = inter.calls[0]["input"]
    assert [x["type"] for x in parts] == ["image", "text"]
    assert inter.calls[0]["generation_config"]["video_config"]["task"] == "image_to_video"


def test_references_use_reference_to_video_with_start_image_first(fake_auth, tmp_path):
    p, inter = provider(fake_auth)
    a, b, c = (write(tmp_path, n, raw) for n, raw in (("a.png", PNG), ("b.jpg", JPEG), ("c.png", PNG)))
    out = p.generate("x", image_url=a, reference_image_urls=[b, c])
    assert out["task"] == "reference_to_video" and out["references_used"] == 3
    assert inter.calls[0]["input"][0]["mime_type"] == "image/png"
    assert inter.calls[0]["input"][1]["mime_type"] == "image/jpeg"

    out = p.generate("x", reference_image_urls=[b])  # references alone: still reference_to_video
    assert out["task"] == "reference_to_video"


def test_reference_count_clamped(fake_auth, tmp_path):
    files = [write(tmp_path, f"{i}.png", PNG) for i in range(8)]
    p, inter = provider(fake_auth)
    out = p.generate("x", reference_image_urls=files)
    assert out["references_used"] == models.VIDEO_MAX_REFS and out["references_dropped"] == 2


def test_video_reference_is_rejected(fake_auth, tmp_path):
    clip = write(tmp_path, "clip.mp4", fake_mp4())
    p, inter = provider(fake_auth)
    out = p.generate("make it like this", reference_image_urls=[clip])
    assert out["success"] is False and out["error_type"] == "invalid_request" and "videos are not supported" in out["error"]
    assert inter.calls == []


def test_unsupported_parameters_are_reported_not_sent(fake_auth):
    p, inter = provider(fake_auth)
    out = p.generate("x", negative_prompt="blurry", seed=7, audio=False, upscale=True)
    assert out["success"] and set(out["ignored_parameters"]) == {"negative_prompt", "seed", "audio=false"}
    assert "negative_prompt" not in str(inter.calls[0]) and "seed" not in str(inter.calls[0])


def test_validation_errors(fake_auth):
    p, inter = provider(fake_auth)
    assert p.generate("  ")["error_type"] == "invalid_request"
    p2, _ = provider(fake_auth, configured=False)
    assert p2.generate("x")["error_type"] == "missing_credentials"
    assert inter.calls == []


def test_api_errors_are_classified_and_redacted(fake_auth):
    class Bad(Exception):
        code = 400

    p, _ = provider(fake_auth, exc=Bad("Request blocked by safety policy key=AIzaSyABCDEFGHIJKLMNOPQRSTUV123456"))
    out = p.generate("x")
    assert out["error_type"] == "content_blocked" and "AIza" not in out["error"]

    class Auth(Exception):
        code = 403

    assert provider(fake_auth, exc=Auth("PERMISSION_DENIED"))[0].generate("x")["error_type"] == "auth_error"


def test_no_video_returned(fake_auth):
    empty = NS(output_video=None, output_text="", status="completed", id="i")
    assert provider(fake_auth, empty)[0].generate("x")["error_type"] == "provider_error"
    refused = NS(output_video=None, output_text="I cannot make that video.", status="completed", id="i")
    assert provider(fake_auth, refused)[0].generate("x")["error_type"] == "content_blocked"


def test_capabilities_match_measured_limits(fake_auth):
    caps = GeminiVideoGenProvider(fake_auth()).capabilities()
    assert (caps["min_duration"], caps["max_duration"]) == (3, 10)
    assert caps["aspect_ratios"] == ["16:9", "9:16"] and caps["max_reference_images"] == 6


def test_hung_request_becomes_timeout_error(fake_auth, monkeypatch):
    import time

    class Slow:
        def create(self, **kwargs):
            time.sleep(5)

    monkeypatch.setattr(config, "timeout_seconds", lambda kind, default: 0.2)
    p = GeminiVideoGenProvider(fake_auth(), client_factory=lambda auth, timeout_s: NS(interactions=Slow()))
    started = time.time()
    out = p.generate("x")
    assert out["success"] is False and out["error_type"] == "timeout"
    assert time.time() - started < 2
