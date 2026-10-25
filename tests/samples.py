# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace as NS


def item(name, display="", actions=("generateContent", "countTokens")):
    return NS(name=name, display_name=display, supported_actions=list(actions))


LIVE_SAMPLE = [
    item("models/gemini-2.5-flash-image", "Nano Banana"),
    item("models/gemini-3-pro-image-preview", "Nano Banana Pro"),
    item("models/gemini-3-pro-image", "Nano Banana Pro"),
    item("models/nano-banana-pro-preview", "Nano Banana Pro"),
    item("models/gemini-3.1-flash-image", "Nano Banana 2"),
    item("models/gemini-3.1-flash-lite-image", "Nano Banana 2 Lite"),
    item("models/gemini-nano-banana-2.1", "Nano Banana 2.1"),
    item("models/gemini-omni-flash-preview", "Gemini Omni Flash Preview"),
    item("models/gemini-omni-1.1-flash", "Gemini Omni 1.1 Flash"),
    item("models/gemini-3.8-flash", "Gemini 3.8 Flash"),
    item("models/gemini-3.8-flash-tts", "TTS", ("generateContent",)),
    item("models/gemini-embedding-001", "Embedding", ("embedContent",)),
    item("models/gemini-3.8-live", "Live", ("bidiGenerateContent",)),
]
