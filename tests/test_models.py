# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
import pytest

from hermes_gemini_media import models
from samples import LIVE_SAMPLE


@pytest.mark.parametrize(
    "model_id, actions, expected",
    [
        ("gemini-nano-banana-2.1", ("generateContent",), models.IMAGE),
        ("gemini-3.1-flash-image", (), models.IMAGE),
        ("imagen-4.0-generate-001", ("predict",), models.IMAGE),
        ("gemini-omni-1.1-flash", ("generateContent",), models.VIDEO),
        ("veo-9.0", ("predictLongRunning",), models.VIDEO),
        ("gemini-3.8-flash", ("generateContent",), None),
        ("gemini-3.8-flash-tts", ("generateContent",), None),
        ("gemini-embedding-001", ("embedContent",), None),
        ("some-image-model", ("countTokens",), None),  # cannot generate
    ],
)
def test_classify(model_id, actions, expected):
    assert models.classify(model_id, actions) == expected


def test_parse_filters_dedupes_and_orders():
    parsed = models.parse_sdk_models(LIVE_SAMPLE)
    ids = [m.id for m in parsed]
    image_ids = [m.id for m in parsed if m.kind == models.IMAGE]
    video_ids = [m.id for m in parsed if m.kind == models.VIDEO]

    assert image_ids == [
        "gemini-nano-banana-2.1",
        "gemini-3.1-flash-lite-image",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image",
    ]
    # preview dropped when GA exists, alias hidden, non-media models excluded
    assert "gemini-3-pro-image-preview" not in ids
    assert "nano-banana-pro-preview" not in ids
    assert "gemini-3.8-flash" not in ids and "gemini-3.8-flash-tts" not in ids
    # curated first, uncurated preview kept and labelled
    assert video_ids == ["gemini-omni-1.1-flash", "gemini-omni-flash-preview"]
    preview = next(m for m in parsed if m.id == "gemini-omni-flash-preview")
    assert preview.preview and "preview" in preview.picker_row()["display"].lower()


def test_static_catalog_has_defaults():
    ids = [m.id for m in models.static_catalog()]
    assert "gemini-nano-banana-2.1" in ids and "gemini-omni-1.1-flash" in ids


def test_default_id_prefers_constant_then_first(fake_auth):
    cat = models.parse_sdk_models(LIVE_SAMPLE)
    assert models.default_id(models.IMAGE, cat) == "gemini-nano-banana-2.1"
    only_old = [m for m in cat if m.id == "gemini-2.5-flash-image"]
    assert models.default_id(models.IMAGE, only_old) == "gemini-2.5-flash-image"
    assert models.default_id(models.VIDEO, only_old) == "gemini-omni-1.1-flash"  # constant when none offered


def test_get_catalog_live_then_memory_then_disk(fake_auth):
    calls = []

    def fetcher(auth):
        calls.append(1)
        return models.parse_sdk_models(LIVE_SAMPLE)

    auth = fake_auth()
    cat, source = models.get_catalog(auth, fetcher=fetcher, now=1000.0)
    assert source == "live" and calls == [1] and cat

    _, source = models.get_catalog(auth, fetcher=fetcher, now=1010.0)
    assert source == "memory" and calls == [1]

    models._memory.clear()  # new process: only the disk copy remains
    cat2, source = models.get_catalog(auth, fetcher=fetcher, now=1020.0)
    assert source == "disk" and calls == [1]
    assert [m.id for m in cat2] == [m.id for m in cat]


def test_get_catalog_ttl_expiry_and_force_refresh(fake_auth):
    calls = []

    def fetcher(auth):
        calls.append(1)
        return models.parse_sdk_models(LIVE_SAMPLE)

    auth = fake_auth()
    models.get_catalog(auth, fetcher=fetcher, now=0.0, ttl_s=100)
    _, source = models.get_catalog(auth, fetcher=fetcher, now=500.0, ttl_s=100)
    assert source == "live" and len(calls) == 2
    _, source = models.get_catalog(auth, fetcher=fetcher, now=501.0, ttl_s=100, force_refresh=True)
    assert source == "live" and len(calls) == 3


def test_get_catalog_failure_falls_back_to_static_without_raising(fake_auth):
    def boom(auth):
        raise RuntimeError("network down")

    cat, source = models.get_catalog(fake_auth(), fetcher=boom)
    assert source == "static"
    assert [m.id for m in cat] == [m.id for m in models.static_catalog()]


def test_get_catalog_empty_live_result_uses_static(fake_auth):
    _, source = models.get_catalog(fake_auth(), fetcher=lambda a: [])
    assert source == "static"


def test_get_catalog_unconfigured_never_calls_fetcher(fake_auth):
    def fetcher(auth):
        raise AssertionError("must not be called")

    _, source = models.get_catalog(fake_auth(configured=False), fetcher=fetcher)
    assert source == "static"


def test_cache_is_keyed_by_credential(fake_auth):
    calls = []

    def fetcher(auth):
        calls.append(auth.fingerprint())
        return models.parse_sdk_models(LIVE_SAMPLE)

    models.get_catalog(fake_auth(fingerprint="aaa"), fetcher=fetcher, now=1.0)
    _, source = models.get_catalog(fake_auth(fingerprint="bbb"), fetcher=fetcher, now=2.0)
    assert source == "live" and calls == ["aaa", "bbb"]


def test_disk_cache_never_contains_the_key(fake_auth, tmp_path):
    secret = "AIzaSyDUMMYKEY0123456789abcdefghijk"

    class Auth(fake_auth):
        def client_kwargs(self):
            return {"api_key": secret}

    models.get_catalog(Auth(), fetcher=lambda a: models.parse_sdk_models(LIVE_SAMPLE), now=1.0)
    path = models._cache_path()
    assert path is not None and path.is_file()
    assert secret not in path.read_text(encoding="utf-8")
