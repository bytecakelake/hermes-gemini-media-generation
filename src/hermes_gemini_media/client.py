# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
"""``google-genai`` client factory. The only module that constructs SDK clients, so the SDK can
be swapped or wrapped (e.g. an OAuth transport in Phase 6) in one place."""

from __future__ import annotations

import importlib.util
import threading
from typing import Any, Callable

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


class DeadlineExceeded(TimeoutError):
    """The wall-clock deadline passed before the SDK call returned."""


def call_with_deadline(fn: Callable[[], Any], seconds: float) -> Any:
    """Run ``fn`` and give up after ``seconds`` of wall-clock time.

    The SDK's own ``timeout`` is per HTTP phase and its retry layer can stretch one call far past
    it (observed: a video request still waiting after 7 minutes). The worker is a daemon thread, so
    an abandoned call cannot block interpreter exit; it is left to finish and its result discarded.
    """
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=worker, name="gemini-media-call", daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise DeadlineExceeded(f"Gemini did not respond within {int(seconds)} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def response_format_kwargs(response_format: dict[str, Any]) -> dict[str, Any]:
    """Keyword arguments that deliver ``response_format`` intact on every supported SDK version.

    Hermes pins ``google-auth``, which caps ``google-genai`` at 2.12.x on a stock install. That
    release silently drops response-format fields it does not model yet (``resolution`` for video).
    ``extra_body`` is sent verbatim and replaces the typed field, so passing the same complete dict
    through both keeps newer SDKs unchanged and makes older ones lossless.
    """
    return {"response_format": response_format, "extra_body": {"response_format": response_format}}
