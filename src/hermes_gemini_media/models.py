# Copyright 2026 bytecakaleke
# SPDX-License-Identifier: Apache-2.0
"""Model catalog built from the Gemini ``models.list`` endpoint.

``models.list`` says which model ids exist for this key and which methods they support; it does NOT
say whether a model outputs images or video, nor its resolutions / reference limits. So:

* the live list decides *availability*,
* id patterns (``image`` / ``nano-banana`` -> image, ``omni`` / ``veo`` -> video) decide *kind*,
* the curated table below decides *order, labels and capabilities*.

``list_models`` is called by the ``hermes tools`` picker on every paint, so it must be fast and must
never raise: results are cached in memory and on disk (24h) and fall back to the curated table when
the endpoint is unreachable.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .auth import AuthStrategy
from .constants import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    MODELS_CACHE_DIRNAME,
    MODELS_CACHE_FILENAME,
    MODELS_CACHE_TTL_S,
    MODELS_LIST_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

IMAGE = "image"
VIDEO = "video"

# --- curated knowledge (verify against docs when bumping; sources: ai.google.dev, 2026-10) ----------
# rank: lower sorts first. Unlisted live models sort after curated ones, alphabetically.
CURATED: dict[str, dict[str, Any]] = {
    "gemini-nano-banana-2.1": {
        "kind": IMAGE, "rank": 0, "display": "Nano Banana 2.1",
        "strengths": "Current workhorse: fast, 1K/2K/4K, Google Search grounding, multi-reference",
    },
    "gemini-3.1-flash-lite-image": {
        "kind": IMAGE, "rank": 1, "display": "Nano Banana 2 Lite",
        "strengths": "Fastest and cheapest; 1K only; weak with many references",
    },
    "gemini-3.1-flash-image": {
        "kind": IMAGE, "rank": 2, "display": "Nano Banana 2",
        "strengths": "Previous-generation workhorse; 512px to 4K",
    },
    "gemini-3-pro-image": {
        "kind": IMAGE, "rank": 3, "display": "Nano Banana Pro",
        "strengths": "Premium: complex scenes, text rendering, highest world knowledge",
    },
    "gemini-2.5-flash-image": {
        "kind": IMAGE, "rank": 4, "display": "Nano Banana (legacy)",
        "strengths": "Legacy model; prefer Nano Banana 2.1 / 2 Lite",
    },
    "gemini-omni-1.1-flash": {
        "kind": VIDEO, "rank": 0, "display": "Gemini Omni 1.1 Flash",
        "strengths": "Text/image/reference-to-video with native audio; 16:9 and 9:16; 360p-4K (upscaled)",
    },
}
# Aliases that point at a model already listed under its canonical id.
HIDDEN = {"nano-banana-pro-preview"}

_VIDEO_RE = re.compile(r"omni|veo", re.I)
_IMAGE_RE = re.compile(r"image|nano-banana|imagen", re.I)
_EXCLUDE_RE = re.compile(r"tts|embed|live|aqa|audio|robotics|computer-use|learnlm|gemma", re.I)
_GENERATE_ACTIONS = {"generateContent", "predict", "predictLongRunning"}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    kind: str
    display: str = ""
    actions: tuple[str, ...] = ()
    preview: bool = False
    curated: bool = False
    strengths: str = ""
    rank: int = 1000

    def picker_row(self) -> dict[str, Any]:
        label = self.display or self.id
        if self.preview and "preview" not in label.lower():
            label += " (preview)"
        row: dict[str, Any] = {"id": self.id, "display": label}
        if self.strengths:
            row["strengths"] = self.strengths
        return row


def _strip(name: str) -> str:
    return name[len("models/"):] if name.startswith("models/") else name


def classify(model_id: str, actions: tuple[str, ...] = ()) -> Optional[str]:
    """``"image"``, ``"video"`` or ``None`` (not a media-generation model)."""
    if _EXCLUDE_RE.search(model_id):
        return None
    usable = (not actions) or bool(_GENERATE_ACTIONS.intersection(actions))
    if not usable:
        return None
    if _VIDEO_RE.search(model_id):
        return VIDEO
    if _IMAGE_RE.search(model_id):
        return IMAGE
    return None


def _build(model_id: str, display: str, actions: tuple[str, ...]) -> Optional[ModelInfo]:
    meta = CURATED.get(model_id)
    kind = meta["kind"] if meta else classify(model_id, actions)
    if kind is None:
        return None
    return ModelInfo(
        id=model_id,
        kind=kind,
        display=(meta or {}).get("display") or display or model_id,
        actions=actions,
        preview="preview" in model_id.lower(),
        curated=meta is not None,
        strengths=(meta or {}).get("strengths", ""),
        rank=(meta or {}).get("rank", 1000),
    )


def _order(models: list[ModelInfo]) -> list[ModelInfo]:
    ids = {m.id for m in models}
    kept = []
    for m in models:
        if m.id in HIDDEN:
            continue
        # drop "<x>-preview" when the GA id "<x>" is listed too
        if m.preview and m.id.replace("-preview", "") in ids:
            continue
        kept.append(m)
    return sorted(kept, key=lambda m: (m.kind, m.rank, m.id))


def parse_sdk_models(items: Any) -> list[ModelInfo]:
    """Turn ``client.models.list()`` items into media ``ModelInfo`` rows (ordered, deduped)."""
    out: dict[str, ModelInfo] = {}
    for item in items:
        name = getattr(item, "name", None)
        if not isinstance(name, str) or not name:
            continue
        model_id = _strip(name)
        actions = tuple(getattr(item, "supported_actions", None) or ())
        info = _build(model_id, getattr(item, "display_name", "") or "", actions)
        if info is not None:
            out[model_id] = info
    return _order(list(out.values()))


def static_catalog() -> list[ModelInfo]:
    """Curated fallback used when the live list is unavailable."""
    return _order([m for mid, meta in CURATED.items() if (m := _build(mid, meta["display"], ()))])


# --- cache -----------------------------------------------------------------------------------------
_lock = threading.Lock()
_memory: dict[str, tuple[float, list[ModelInfo]]] = {}


def _cache_path() -> Optional[Path]:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()) / "cache" / MODELS_CACHE_DIRNAME / MODELS_CACHE_FILENAME
    except Exception:
        return None


def _mem_key(fingerprint: str) -> str:
    path = _cache_path()
    return f"{path}|{fingerprint}"


def _read_disk(fingerprint: str, ttl_s: float, now: float) -> Optional[list[ModelInfo]]:
    path = _cache_path()
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") != fingerprint or now - float(data["fetched_at"]) > ttl_s:
            return None
        return [ModelInfo(**{**m, "actions": tuple(m.get("actions", ()))}) for m in data["models"]]
    except Exception as exc:
        logger.debug("models cache unreadable: %s", type(exc).__name__)
        return None


def _write_disk(fingerprint: str, models: list[ModelInfo], now: float) -> None:
    path = _cache_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"fingerprint": fingerprint, "fetched_at": now, "models": [asdict(m) for m in models]}),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as exc:
        logger.debug("models cache not written: %s", type(exc).__name__)


def clear_cache() -> None:
    with _lock:
        _memory.clear()
    path = _cache_path()
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def fetch_live(auth: AuthStrategy, *, client_factory: Optional[Callable[..., Any]] = None) -> list[ModelInfo]:
    """Call ``models.list`` (paginated by the SDK). Raises on failure."""
    if client_factory is None:
        from .client import build_client as client_factory  # type: ignore[assignment]
    client = client_factory(auth, timeout_s=MODELS_LIST_TIMEOUT_S)
    return parse_sdk_models(client.models.list())


def get_catalog(
    auth: AuthStrategy,
    *,
    force_refresh: bool = False,
    ttl_s: float = MODELS_CACHE_TTL_S,
    fetcher: Optional[Callable[[AuthStrategy], list[ModelInfo]]] = None,
    now: Optional[float] = None,
) -> tuple[list[ModelInfo], str]:
    """Return ``(models, source)`` where source is ``memory|disk|live|static``. Never raises."""
    now = time.time() if now is None else now
    if not auth.is_configured():
        return static_catalog(), "static"
    fingerprint = auth.fingerprint()
    key = _mem_key(fingerprint)
    with _lock:
        if not force_refresh:
            hit = _memory.get(key)
            if hit and now - hit[0] <= ttl_s:
                return hit[1], "memory"
    if not force_refresh:
        disk = _read_disk(fingerprint, ttl_s, now)
        if disk is not None:
            with _lock:
                _memory[key] = (now, disk)
            return disk, "disk"
    try:
        live = (fetcher or fetch_live)(auth)
    except Exception as exc:
        logger.debug("models.list failed (%s); using static catalog", type(exc).__name__)
        return static_catalog(), "static"
    if not live:
        return static_catalog(), "static"
    with _lock:
        _memory[key] = (now, live)
    _write_disk(fingerprint, live, now)
    return live, "live"


def models_of(kind: str, catalog: list[ModelInfo]) -> list[ModelInfo]:
    return [m for m in catalog if m.kind == kind]


def default_id(kind: str, catalog: list[ModelInfo]) -> Optional[str]:
    """Preferred default if offered, else the first offered model of that kind, else the constant."""
    preferred = DEFAULT_IMAGE_MODEL if kind == IMAGE else DEFAULT_VIDEO_MODEL
    of_kind = models_of(kind, catalog)
    ids = [m.id for m in of_kind]
    if preferred in ids:
        return preferred
    return ids[0] if ids else preferred
