# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Provider tests subclass Hermes's ABCs, so a Hermes source tree must be importable.
_default_hermes = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"
HERMES_DIR = Path(os.environ.get("HERMES_AGENT_DIR", _default_hermes))
if HERMES_DIR.is_dir():
    sys.path.insert(0, str(HERMES_DIR))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch, request):
    """Every test gets its own HERMES_HOME and a clean in-memory model cache, and no real key."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    live = request.node.get_closest_marker("live") is not None
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_IMAGE_MODEL", "GEMINI_VIDEO_MODEL"):
        if live and name == "GEMINI_API_KEY":
            continue  # live tests need the real key
        monkeypatch.delenv(name, raising=False)
    from hermes_gemini_media import models

    models.clear_cache()
    yield
    models.clear_cache()


class FakeAuth:
    """AuthStrategy stand-in that never reads the environment."""

    name = "fake"

    def __init__(self, configured=True, fingerprint="fp1"):
        self.configured = configured
        self._fp = fingerprint

    def is_configured(self):
        return self.configured

    def client_kwargs(self):
        return {"api_key": "unused"}

    def fingerprint(self):
        return self._fp

    def missing_message(self):
        return "missing"


@pytest.fixture
def fake_auth():
    return FakeAuth
