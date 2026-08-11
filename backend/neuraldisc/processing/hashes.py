"""Perceptual hash computation."""

from __future__ import annotations

from pathlib import Path

import imagehash
from PIL import Image

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


def compute_perceptual_hashes(path: Path) -> tuple[str | None, str | None]:
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            ph = str(imagehash.phash(im))
            dh = str(imagehash.dhash(im))
            return ph, dh
    except Exception as exc:  # noqa: BLE001
        log.debug("phash_failed", path=str(path), error=str(exc))
        return None, None


def hamming_hex(a: str, b: str) -> int:
    """Hamming distance between two hex hash strings."""
    try:
        ha = imagehash.hex_to_hash(a)
        hb = imagehash.hex_to_hash(b)
        return ha - hb
    except Exception:  # noqa: BLE001
        return 999
