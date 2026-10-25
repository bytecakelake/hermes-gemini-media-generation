# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
import base64
from types import SimpleNamespace as NS

import pytest

from hermes_gemini_media import config, media_io, models
from hermes_gemini_media.image_provider import GeminiImageGenProvider
from samples import LIVE_SAMPLE

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class FakeInteractions:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.result


def ok_result(mime="image/jpeg", data=JPEG):
    return NS(
        output_image=NS(data=base64.b64encode(data).decode(), mime_type=mime),
        output_text="", status="completed", id="v1_abc",
    )


def provider(fake_auth, result=None, exc=None, configured=True):
    interactions = FakeInteractions(result if result is not None else ok_result(), exc)
    p = GeminiImageGenProvider(
        fake_auth(configured=configured),
        client_factory=lambda auth, timeout_s: NS(interactions=interactions),
    )
    return p, interactions


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    cat = models.parse_sdk_models(LIVE_SAMPLE)
    monkeypatch.setattr(models, "get_catalog", lambda auth, **kw: (cat, "live"))
    monkeypatch.setattr(config, "_load_config", lambda: {})


def test_text_to_image_success(fake_auth):
    p, inter = provider(fake_auth)
    out = p.generate("a red apple", "landscape")
    assert out["success"] is True
    assert out["model"] == "gemini-nano-banana-2.1"
    assert out["modality"] == "text" and out["aspect_ratio"] == "landscape"
    assert out["image"].endswith(".jpg")
    with open(out["image"], "rb") as fh:
        assert fh.read() == JPEG
    assert out["gemini_aspect_ratio"] == "16:9" and out["references_used"] == 0
    assert out["interaction_id"] == "v1_abc"
    call = inter.calls[0]
    assert call["input"] == "a red apple"
    assert call["response_format"] == {"type": "image", "aspect_ratio": "16:9"}


@pytest.mark.parametrize("aspect, expected", [("square", "1:1"), ("portrait", "9:16"), ("bogus", "16:9")])
def test_aspect_mapping(fake_auth, aspect, expected):
    p, inter = provider(fake_auth)
    assert p.generate("x", aspect)["success"]
    assert inter.calls[0]["response_format"]["aspect_ratio"] == expected


def test_png_result_uses_png_extension(fake_auth):
    p, _ = provider(fake_auth, ok_result("image/png", PNG))
    assert p.generate("x")["image"].endswith(".png")


def test_references_go_before_prompt_with_image_url_first(fake_auth, tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.jpg"
    a.write_bytes(PNG)
    b.write_bytes(JPEG)
    data_uri = "data:image/png;base64," + base64.b64encode(PNG).decode()
    p, inter = provider(fake_auth)
    out = p.generate("combine", "square", image_url=str(a), reference_image_urls=[str(b), data_uri])
    assert out["success"] and out["modality"] == "image" and out["references_used"] == 3
    parts = inter.calls[0]["input"]
    assert [x["type"] for x in parts] == ["image", "image", "image", "text"]
    assert parts[0]["mime_type"] == "image/png" and parts[1]["mime_type"] == "image/jpeg"
    assert parts[-1] == {"type": "text", "text": "combine"}


def test_reference_count_is_clamped_to_model_limit(fake_auth, tmp_path, monkeypatch):
    monkeypatch.setitem(models.IMAGE_LIMITS, "tiny-image", {"sizes": ("1K",), "max_refs": 2})
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "tiny-image")
    files = []
    for i in range(4):
        f = tmp_path / f"{i}.png"
        f.write_bytes(PNG)
        files.append(str(f))
    p, inter = provider(fake_auth)
    out = p.generate("x", reference_image_urls=files)
    assert out["success"] and out["references_used"] == 2 and out["references_dropped"] == 2
    assert len(inter.calls[0]["input"]) == 3


def test_image_size_from_settings_is_clamped_per_model(fake_auth, monkeypatch):
    cfg = {"image_gen": {"gemini": {"image_size": "4k", "model": "gemini-3.1-flash-lite-image"}}}
    monkeypatch.setattr(config, "_load_config", lambda: cfg)
    p, inter = provider(fake_auth)
    out = p.generate("x")
    assert inter.calls[0]["model"] == "gemini-3.1-flash-lite-image"
    assert inter.calls[0]["response_format"]["image_size"] == "1K"  # lite supports 1K only
    assert out["image_size"] == "1K" and out["image_size_adjusted"] is True

    cfg["image_gen"]["gemini"]["model"] = "gemini-nano-banana-2.1"
    out = p.generate("x")
    assert out["image_size"] == "4K" and "image_size_adjusted" not in out


@pytest.mark.parametrize("make", [
    lambda tmp: (tmp / "missing.png"),
    lambda tmp: _write(tmp / "clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16),
    lambda tmp: _write(tmp / "notes.txt", b"hello"),
])
def test_bad_references_are_invalid_request(fake_auth, tmp_path, make):
    p, inter = provider(fake_auth)
    out = p.generate("x", image_url=str(make(tmp_path)))
    assert out["success"] is False and out["error_type"] == "invalid_request"
    assert inter.calls == []  # never reaches the API


def _write(path, raw):
    path.write_bytes(raw)
    return path


def test_private_url_reference_is_refused(fake_auth):
    p, inter = provider(fake_auth)
    out = p.generate("x", image_url="http://127.0.0.1:8080/secret.png")
    assert out["error_type"] == "invalid_request" and inter.calls == []


def test_public_url_reference_is_downloaded(fake_auth, monkeypatch):
    monkeypatch.setattr(media_io, "_download", lambda url: PNG)
    monkeypatch.setattr(media_io, "url_allowed", lambda url: True)
    p, inter = provider(fake_auth)
    out = p.generate("x", image_url="https://example.com/a.png")
    assert out["success"] and out["references_used"] == 1


def test_validation_errors(fake_auth):
    p, inter = provider(fake_auth)
    assert p.generate("   ")["error_type"] == "invalid_request"
    p2, _ = provider(fake_auth, configured=False)
    assert p2.generate("x")["error_type"] == "missing_credentials"
    assert inter.calls == []


def test_api_exception_is_classified_and_redacted(fake_auth):
    class Boom(Exception):
        code = 429

    p, _ = provider(fake_auth, exc=Boom("quota hit ?key=AIzaSyABCDEFGHIJKLMNOPQRSTUV123456"))
    out = p.generate("x")
    assert out["success"] is False and out["error_type"] == "rate_limited"
    assert "AIza" not in out["error"]


def test_no_image_returned_is_reported(fake_auth):
    refused = NS(output_image=None, output_text="I can't create that because of safety policy.", status="completed", id="i")
    out, _ = provider(fake_auth, refused)[0].generate("x"), None
    assert out["error_type"] == "content_blocked" and "safety" in out["error"]

    empty = NS(output_image=None, output_text="", status="completed", id="i")
    out = provider(fake_auth, empty)[0].generate("x")
    assert out["error_type"] == "provider_error"


def test_unknown_kwargs_are_ignored(fake_auth):
    p, _ = provider(fake_auth)
    assert p.generate("x", upscale=True, creativity=3, whatever=1)["success"]
