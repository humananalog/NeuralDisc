"""Blur detection via Laplacian variance.

Lower variance ⇒ smoother image ⇒ more blur.
Runs on a downscaled grayscale version for speed (import throughput).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# Working size for analysis (long edge)
_MAX_EDGE = 800


@dataclass(frozen=True)
class BlurResult:
    score: float  # Laplacian variance (higher = sharper)
    is_blurry: bool
    threshold: float
    method: str = "laplacian_variance"


def detect_blur(
    path: Path,
    *,
    threshold: float = 80.0,
    max_edge: int = _MAX_EDGE,
) -> BlurResult | None:
    """Return blur metrics for an image file, or None if unreadable."""
    try:
        with Image.open(path) as im:
            im = im.convert("L")
            # EXIF orientation
            try:
                from PIL import ImageOps

                im = ImageOps.exif_transpose(im) or im
                im = im.convert("L")
            except Exception:  # noqa: BLE001
                pass
            im.thumbnail((max_edge, max_edge), Image.Resampling.BILINEAR)
            gray = np.asarray(im, dtype=np.float64)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.debug("blur_unreadable", path=str(path), error=str(exc))
        return None

    if gray.size < 100 or gray.shape[0] < 8 or gray.shape[1] < 8:
        return None

    score = _laplacian_variance(gray)
    return BlurResult(
        score=round(score, 3),
        is_blurry=score < threshold,
        threshold=threshold,
    )


def _laplacian_variance(gray: np.ndarray) -> float:
    """Variance of discrete Laplacian response (classic focus measure)."""
    # Interior Laplacian: center*-4 + 4-neighbours
    center = gray[1:-1, 1:-1]
    lap = (
        -4.0 * center
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(lap.var())
