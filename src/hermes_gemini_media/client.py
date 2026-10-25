# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""``google-genai`` client factory. The only module that constructs SDK clients, so the SDK can
be swapped or wrapped (e.g. an OAuth transport in Phase 6) in one place."""

from __future__ import annotations

import importlib.util
from typing import Any

from .auth import AuthStrategy


def sdk_available() -> bool:
    """True when ``google.genai`` is importable. Cheap: does not import the SDK."""
    try:
        return importlib.util.find_spec("google.genai") is not None
    except (ImportError, ValueError):
        return False


def build_client(auth: AuthStrategy, *, timeout_s: float) -> Any:
    """Create a ``genai.Client`` with a per-request timeout (seconds)."""
    from google import genai
    from google.genai import types

    http_options = types.HttpOptions(timeout=int(timeout_s * 1000))
    return genai.Client(http_options=http_options, **auth.client_kwargs())
