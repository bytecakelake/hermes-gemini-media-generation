# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Map SDK / transport exceptions to Hermes ``error_type`` strings and scrub secrets.

Hermes's own providers use: ``invalid_request``, ``missing_credentials``, ``missing_dependency``,
``no_model``, ``provider_error``. We add the Gemini-specific ones below.
"""

from __future__ import annotations

import re

AUTH_ERROR = "auth_error"
RATE_LIMITED = "rate_limited"
CONTENT_BLOCKED = "content_blocked"
INVALID_REQUEST = "invalid_request"
TIMEOUT = "timeout"
NO_MODEL = "no_model"
PROVIDER_ERROR = "provider_error"
MISSING_CREDENTIALS = "missing_credentials"
MISSING_DEPENDENCY = "missing_dependency"

_KEY_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(x-goog-api-key|api[_-]?key|key)=([^&\s\"']+)"),
)
_SAFETY_WORDS = ("safety", "blocked", "prohibited", "policy", "recitation")


def redact(text: str) -> str:
    """Remove anything that looks like an API key from ``text``."""
    out = str(text)
    out = _KEY_PATTERNS[0].sub("[REDACTED]", out)
    out = _KEY_PATTERNS[1].sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    return out


def _status_code(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_type, message)`` for an exception raised while talking to Gemini."""
    message = redact(str(getattr(exc, "message", None) or exc) or type(exc).__name__)
    lowered = message.lower()
    code = _status_code(exc)
    name = type(exc).__name__.lower()

    if "timeout" in name or "deadline" in name or "timed out" in lowered or "timeout" in lowered or "did not respond" in lowered:
        return TIMEOUT, message
    if code in (401, 403) or "permission_denied" in lowered or "unauthenticated" in lowered:
        return AUTH_ERROR, message
    if code == 429 or "resource_exhausted" in lowered or "quota" in lowered:
        return RATE_LIMITED, message
    if code == 404 or "not found" in lowered:
        return NO_MODEL, message
    if code == 400:
        if any(word in lowered for word in _SAFETY_WORDS):
            return CONTENT_BLOCKED, message
        return INVALID_REQUEST, message
    return PROVIDER_ERROR, message
