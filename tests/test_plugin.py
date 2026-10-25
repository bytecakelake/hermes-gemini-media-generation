# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
from hermes_gemini_media import models
from hermes_gemini_media.image_provider import GeminiImageGenProvider
from hermes_gemini_media.plugin import register
from hermes_gemini_media.video_provider import GeminiVideoGenProvider
from samples import LIVE_SAMPLE


class FakeCtx:
    def __init__(self):
        self.images, self.videos = [], []

    def register_image_gen_provider(self, provider):
        self.images.append(provider)

    def register_video_gen_provider(self, provider):
        self.videos.append(provider)


def _patch_catalog(monkeypatch):
    cat = models.parse_sdk_models(LIVE_SAMPLE)
    monkeypatch.setattr(models, "get_catalog", lambda auth, **kw: (cat, "live"))


def test_register_registers_both_backends():
    ctx = FakeCtx()
    register(ctx)
    assert [type(p) for p in ctx.images] == [GeminiImageGenProvider]
    assert [type(p) for p in ctx.videos] == [GeminiVideoGenProvider]
    assert ctx.images[0].name == ctx.videos[0].name == "gemini"


def test_is_available_requires_key_and_never_hits_network(fake_auth, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("is_available() must not call the network")

    monkeypatch.setattr(models, "get_catalog", forbidden)
    assert GeminiImageGenProvider(fake_auth(configured=True)).is_available()
    assert not GeminiImageGenProvider(fake_auth(configured=False)).is_available()
    assert GeminiVideoGenProvider(fake_auth(configured=True)).is_available()
    assert not GeminiVideoGenProvider(fake_auth(configured=False)).is_available()


def test_image_model_picker(fake_auth, monkeypatch):
    _patch_catalog(monkeypatch)
    p = GeminiImageGenProvider(fake_auth())
    rows = p.list_models()
    assert rows[0]["id"] == "gemini-nano-banana-2.1"
    assert all(set(r) >= {"id", "display"} for r in rows)
    assert p.default_model() == "gemini-nano-banana-2.1"


def test_video_model_picker(fake_auth, monkeypatch):
    _patch_catalog(monkeypatch)
    p = GeminiVideoGenProvider(fake_auth())
    rows = p.list_models()
    assert [r["id"] for r in rows][0] == "gemini-omni-1.1-flash"
    assert rows[0]["modalities"] == ["text", "image"]
    assert p.default_model() == "gemini-omni-1.1-flash"


def test_setup_schema_asks_for_api_key(fake_auth):
    for provider in (GeminiImageGenProvider(fake_auth()), GeminiVideoGenProvider(fake_auth())):
        schema = provider.get_setup_schema()
        assert schema["env_vars"][0]["key"] == "GEMINI_API_KEY"
        assert schema["env_vars"][0]["url"].startswith("https://aistudio.google.com")
