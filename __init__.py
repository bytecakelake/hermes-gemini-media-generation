# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Hermes plugin entry shim.

Hermes looks for ``plugin.yaml`` + ``__init__.py`` at the repo root. All real code lives in
``src/hermes_gemini_media``; this file only makes it importable and delegates ``register``.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from hermes_gemini_media.plugin import register  # noqa: E402,F401
