# Copyright 2026 bytecakelake
# SPDX-License-Identifier: Apache-2.0
"""Load user-supplied reference images (URL, ``data:`` URI or local path) as inline base64.

Gemini accepts PNG, JPEG, WebP, HEIC and HEIF inline; the request body is limited to roughly 20 MB,
so each image and the total are capped here instead of failing late inside the API call.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 18 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 30.0
MAX_REDIRECTS = 3
_REMOTE = ("http://", "https://")


class ReferenceImageError(Exception):
    """A reference image could not be used. ``str(exc)`` is safe to show to the user."""


@dataclass(frozen=True)
class LoadedImage:
    b64: str
    mime_type: str
    size: int
    source_kind: str  # "url" | "data" | "file"


def sniff_mime(raw: bytes) -> Optional[str]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[4:8] == b"ftyp":
        brand = raw[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heim", b"heis"):
            return "image/heif"
    return None


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return False
    return True


def url_allowed(url: str) -> bool:
    """SSRF guard: http(s) only, and the host must resolve to public addresses only."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and _host_is_public(parsed.hostname)


def _download(url: str) -> bytes:
    import httpx

    current = url
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=False) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            if not url_allowed(current):
                raise ReferenceImageError("Reference image URL is not allowed (private or unsafe address).")
            with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                if resp.status_code != 200:
                    raise ReferenceImageError(f"Reference image download failed (HTTP {resp.status_code}).")
                chunks, total = [], 0
                for chunk in resp.iter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise ReferenceImageError("Reference image is larger than 15 MB.")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ReferenceImageError("Too many redirects while downloading the reference image.")


def load_reference(source: str) -> LoadedImage:
    source = source.strip()
    lowered = source.lower()
    if lowered.startswith("data:"):
        header, _, payload = source.partition(",")
        if ";base64" not in header.lower() or not payload:
            raise ReferenceImageError("Only base64 data: URIs are supported for reference images.")
        try:
            raw = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ReferenceImageError("Reference image data: URI is not valid base64.") from exc
        kind = "data"
    elif lowered.startswith(_REMOTE):
        raw = _download(source)
        kind = "url"
    else:
        path = Path(os.path.expanduser(source))
        if not path.is_file():
            raise ReferenceImageError(f"Reference image file not found: {source}")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ReferenceImageError("Reference image is larger than 15 MB.")
        # Read only the header first: a file that is not a supported image (a key file, a .env)
        # is rejected before its contents are ever loaded or sent anywhere.
        with path.open("rb") as handle:
            header = handle.read(16)
            if sniff_mime(header) is None:
                raise ReferenceImageError(
                    "Reference must be a PNG, JPEG, WebP, HEIC or HEIF image (videos are not supported).")
            raw = header + handle.read()
        kind = "file"

    if not raw:
        raise ReferenceImageError("Reference image is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ReferenceImageError("Reference image is larger than 15 MB.")
    mime = sniff_mime(raw)
    if mime is None:
        raise ReferenceImageError("Reference must be a PNG, JPEG, WebP, HEIC or HEIF image (videos are not supported).")
    return LoadedImage(b64=base64.b64encode(raw).decode("ascii"), mime_type=mime, size=len(raw), source_kind=kind)


def load_references(sources: list[str]) -> list[LoadedImage]:
    loaded: list[LoadedImage] = []
    total = 0
    for source in sources:
        image = load_reference(source)
        total += image.size
        if total > MAX_TOTAL_BYTES:
            raise ReferenceImageError("Reference images together are larger than 18 MB.")
        loaded.append(image)
    return loaded


def mp4_duration_seconds(raw: bytes) -> Optional[float]:
    """Duration from the ``mvhd`` atom of an MP4, or None when it cannot be read."""
    import struct

    i = raw.find(b"mvhd")
    if i < 0:
        return None
    try:
        if raw[i + 4] == 0:
            timescale, duration = struct.unpack(">II", raw[i + 16 : i + 24])
        else:
            timescale, duration = struct.unpack(">IQ", raw[i + 24 : i + 36])
    except struct.error:
        return None
    return round(duration / timescale, 2) if timescale else None
