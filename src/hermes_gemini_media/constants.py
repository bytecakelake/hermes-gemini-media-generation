# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Shared constants. Model ids here are defaults only; the live ``models.list`` result decides
what is actually offered (see ``models.py``)."""

PROVIDER_NAME = "gemini"

# Checked in order. GEMINI_API_KEY is the documented name; GOOGLE_API_KEY is what Hermes's native
# Gemini chat provider reads, so accept it too.
API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
API_KEY_URL = "https://aistudio.google.com/apikey"

DEFAULT_IMAGE_MODEL = "gemini-nano-banana-2.1"
DEFAULT_VIDEO_MODEL = "gemini-omni-1.1-flash"

IMAGE_MODEL_ENV = "GEMINI_IMAGE_MODEL"
VIDEO_MODEL_ENV = "GEMINI_VIDEO_MODEL"

# models.list is cached on disk so the `hermes tools` picker never blocks on the network.
MODELS_CACHE_TTL_S = 24 * 3600
MODELS_LIST_TIMEOUT_S = 10.0
MODELS_CACHE_DIRNAME = "gemini_media"
MODELS_CACHE_FILENAME = "models.json"

IMAGE_REQUEST_TIMEOUT_S = 180.0
VIDEO_REQUEST_TIMEOUT_S = 900.0
