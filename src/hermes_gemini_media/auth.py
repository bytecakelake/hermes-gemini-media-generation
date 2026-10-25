# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Credential resolution.

v0.1.0 supports an API key only. ``AuthStrategy`` is the seam where an OAuth strategy can be added
later (Phase 6) without touching providers, the client factory or the model catalog.
"""

from __future__ import annotations

import abc
import hashlib
import logging
import os
from typing import Any, Optional

from .constants import API_KEY_ENV_VARS

logger = logging.getLogger(__name__)


def _read_secret(name: str) -> Optional[str]:
    """Read ``name`` through Hermes's profile-scoped resolver, falling back to ``os.environ``
    when Hermes's module is not importable (unit tests, standalone use)."""
    try:
        from agent.secret_scope import get_secret
    except Exception:  # pragma: no cover - only outside a Hermes process
        value = os.environ.get(name)
    else:
        try:
            value = get_secret(name)
        except Exception as exc:  # fail closed (e.g. multiplexing with no scope)
            logger.debug("secret %s unavailable: %s", name, type(exc).__name__)
            return None
    value = (value or "").strip()
    return value or None


class AuthStrategy(abc.ABC):
    """How requests to the Gemini API are authenticated."""

    name: str = ""

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True when credentials are present. Must not touch the network."""

    @abc.abstractmethod
    def client_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``google.genai.Client`` carrying the credential."""

    @abc.abstractmethod
    def fingerprint(self) -> str:
        """Stable, non-reversible id of the credential (cache key). Never the secret itself."""

    @abc.abstractmethod
    def missing_message(self) -> str:
        """Human-readable fix for an unconfigured strategy."""


class ApiKeyAuth(AuthStrategy):
    name = "api_key"

    def resolve_key(self) -> Optional[str]:
        for env_name in API_KEY_ENV_VARS:
            value = _read_secret(env_name)
            if value:
                return value
        return None

    def is_configured(self) -> bool:
        return self.resolve_key() is not None

    def client_kwargs(self) -> dict[str, Any]:
        key = self.resolve_key()
        if not key:
            raise RuntimeError(self.missing_message())
        return {"api_key": key}

    def fingerprint(self) -> str:
        key = self.resolve_key()
        if not key:
            return "none"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def missing_message(self) -> str:
        return (
            f"No Gemini API key found. Set {API_KEY_ENV_VARS[0]} (get one at "
            "https://aistudio.google.com/apikey) in ~/.hermes/.env or run `hermes tools`. "
            "If you just set it as a system environment variable, restart Hermes."
        )


def default_auth() -> AuthStrategy:
    return ApiKeyAuth()
