# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
import pytest

from hermes_gemini_media import config, errors
from hermes_gemini_media.auth import ApiKeyAuth


def test_api_key_resolution_order(monkeypatch):
    auth = ApiKeyAuth()
    assert not auth.is_configured()
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert auth.resolve_key() == "google-key"
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")  # GEMINI_API_KEY wins
    assert auth.resolve_key() == "gemini-key"
    assert auth.client_kwargs() == {"api_key": "gemini-key"}


def test_blank_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert not ApiKeyAuth().is_configured()


def test_fingerprint_is_not_the_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value-123")
    fp = ApiKeyAuth().fingerprint()
    assert "super-secret" not in fp and len(fp) == 12
    monkeypatch.setenv("GEMINI_API_KEY", "another")
    assert ApiKeyAuth().fingerprint() != fp


def test_client_kwargs_without_key_raises_actionable_message():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        ApiKeyAuth().client_kwargs()


class Boom(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@pytest.mark.parametrize(
    "exc, expected",
    [
        (Boom(401, "bad key"), errors.AUTH_ERROR),
        (Boom(403, "PERMISSION_DENIED"), errors.AUTH_ERROR),
        (Boom(429, "RESOURCE_EXHAUSTED"), errors.RATE_LIMITED),
        (Boom(404, "model not found"), errors.NO_MODEL),
        (Boom(400, "blocked by safety policy"), errors.CONTENT_BLOCKED),
        (Boom(400, "bad field"), errors.INVALID_REQUEST),
        (Boom(500, "internal"), errors.PROVIDER_ERROR),
        (TimeoutError("timed out"), errors.TIMEOUT),
    ],
)
def test_classify_exception(exc, expected):
    assert errors.classify_exception(exc)[0] == expected


def test_redact_removes_keys():
    text = "GET https://x/v1beta/models?key=AIzaSyABCDEFGHIJKLMNOPQRSTUV123456 failed; x-goog-api-key=abc123"
    out = errors.redact(text)
    assert "AIza" not in out and "abc123" not in out and "[REDACTED]" in out
    assert "AIza" not in errors.classify_exception(Boom(400, text))[1]


def test_resolve_model_precedence(monkeypatch):
    ids = ["gemini-nano-banana-2.1", "gemini-3-pro-image"]
    cfg = {"image_gen": {"model": "gemini-3-pro-image", "gemini": {"model": "from-provider-block"}}}
    monkeypatch.setattr(config, "_load_config", lambda: cfg)

    assert config.resolve_model("image", "models/caller", ids) == "caller"
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "from-env")
    assert config.resolve_model("image", None, ids) == "from-env"
    monkeypatch.delenv("GEMINI_IMAGE_MODEL")
    assert config.resolve_model("image", None, ids) == "from-provider-block"

    cfg["image_gen"]["gemini"].pop("model")
    assert config.resolve_model("image", None, ids) == "gemini-3-pro-image"  # shared key, but ours

    cfg["image_gen"]["model"] = "fal-ai/flux-2"  # belongs to another provider: ignored
    assert config.resolve_model("image", None, ids) == "gemini-nano-banana-2.1"


def test_resolve_model_defaults(monkeypatch):
    monkeypatch.setattr(config, "_load_config", lambda: {})
    assert config.resolve_model("video", None, []) == "gemini-omni-1.1-flash"
    assert config.resolve_model("video", None, ["something-else"]) == "something-else"


def test_call_with_deadline_returns_raises_and_times_out():
    import time

    from hermes_gemini_media.client import DeadlineExceeded, call_with_deadline

    assert call_with_deadline(lambda: 42, 5) == 42
    with pytest.raises(ValueError, match="boom"):
        call_with_deadline(lambda: (_ for _ in ()).throw(ValueError("boom")), 5)
    started = time.time()
    with pytest.raises(DeadlineExceeded):
        call_with_deadline(lambda: time.sleep(5), 0.2)
    assert time.time() - started < 2
    assert errors.classify_exception(DeadlineExceeded("Gemini did not respond within 1 s"))[0] == errors.TIMEOUT


def test_timeout_seconds_setting(monkeypatch):
    cfg = {"video_gen": {"gemini": {"timeout_s": 45}}}
    monkeypatch.setattr(config, "_load_config", lambda: cfg)
    assert config.timeout_seconds("video", 300.0) == 45.0
    assert config.timeout_seconds("image", 150.0) == 150.0
    cfg["video_gen"]["gemini"]["timeout_s"] = 99999
    assert config.timeout_seconds("video", 300.0) == 1800.0
