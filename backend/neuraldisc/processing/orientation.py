"""SOTA auto-orientation for still images.

Strategy (photo-catalogue best practice, used by Apple Photos / Immich / digiKam):

1. **EXIF Orientation bake** — apply tag 0x0112 via ImageOps.exif_transpose,
   rewrite pixels so Orientation=1, swap width/height as needed.
2. **Content upright hint** — when EXIF is missing or Orientation=1, score the
   four cardinal rotations (edge energy + sky/top-band bias). Aggressive mode
   (user-triggered batch auto-rotate) uses a lower margin so sideways camera
   JPEGs with Orientation=1 still get fixed.
3. **Manual rotate** — 90° CW / CCW / 180 for human correction.

Rewrites originals in-place (or via temp + replace) and returns updated geometry
so callers can refresh DB hashes / derivatives.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# EXIF Orientation tag id
_ORIENT_TAG = 274

# Formats we can safely rewrite as JPEG derivatives of themselves
_JPEG_EXTS = {".jpg", ".jpeg"}
_PNG_EXTS = {".png"}
_REWRITE_EXTS = _JPEG_EXTS | _PNG_EXTS | {".webp", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True)
class OrientResult:
    changed: bool
    orientation_before: int | None
    orientation_after: int
    width: int | None
    height: int | None
    degrees_applied: int  # clockwise degrees baked into pixels
    method: str  # exif | content | manual | none
    path: str


def read_exif_orientation(path: Path) -> int | None:
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            val = exif.get(_ORIENT_TAG)
            return int(val) if val is not None else None
    except (UnidentifiedImageError, OSError, ValueError, TypeError):
        return None


def _orientation_to_degrees(orient: int | None) -> int:
    """Map EXIF orientation → clockwise degrees needed to upright (approx)."""
    # 1=normal, 3=180, 6=90 CW, 8=90 CCW (=270 CW); flips 2/4/5/7 rare
    mapping = {1: 0, 2: 0, 3: 180, 4: 180, 5: 270, 6: 90, 7: 90, 8: 270}
    if orient is None:
        return 0
    return mapping.get(int(orient), 0)


def _apply_manual_rotate(im: Image.Image, degrees_cw: int) -> Image.Image:
    d = degrees_cw % 360
    if d == 0:
        return im
    if d == 90:
        return im.transpose(Image.Transpose.ROTATE_270)  # PIL is CCW
    if d == 180:
        return im.transpose(Image.Transpose.ROTATE_180)
    if d == 270:
        return im.transpose(Image.Transpose.ROTATE_90)
    return im.rotate(-d, expand=True)


def _score_upright(a: np.ndarray) -> float:
    """Higher = more likely upright for natural photos."""
    if a.shape[0] < 8 or a.shape[1] < 8:
        return 0.0
    # Gradients
    gy = float(np.abs(a[1:, :] - a[:-1, :]).mean())
    gx = float(np.abs(a[:, 1:] - a[:, :-1]).mean())
    # Top/bottom band difference (sky / ground)
    h = a.shape[0]
    top = float(a[: h // 5, :].mean())
    bot = float(a[4 * h // 5 :, :].mean())
    mid = float(a[2 * h // 5 : 3 * h // 5, :].mean())
    sky_band = abs(top - bot) + 0.35 * abs(top - mid)
    # Prefer slightly stronger horizontal structure when upright (horizons, tables)
    return gx * 1.2 + gy * 0.95 + sky_band * 0.08


def _content_upright_degrees(im: Image.Image, *, aggressive: bool = False) -> int:
    """Pick 0/90/180/270 for upright content.

    ``aggressive=True`` (user batch auto-rotate): lower margin so clearly
    sideways images with EXIF Orientation=1 still rotate. Tie-break 90 vs 270
    using top/bottom luminance asymmetry.
    """
    try:
        gray = im.convert("L")
        gray.thumbnail((384, 384), Image.Resampling.BILINEAR)
        arr = np.asarray(gray, dtype=np.float32)
    except Exception:  # noqa: BLE001
        return 0

    rotated = {
        0: arr,
        90: np.rot90(arr, k=3),  # 90 CW
        180: np.rot90(arr, k=2),
        270: np.rot90(arr, k=1),
    }
    scores = {d: _score_upright(a) for d, a in rotated.items()}
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_deg, best_s = ordered[0]
    second_deg, second_s = ordered[1]

    if best_deg == 0:
        # Even if 0 wins, aggressive may force 90/270 when they are close and
        # image is landscape but content strongly prefers a side orientation
        if not aggressive:
            return 0
        side = max((scores[90], 90), (scores[270], 270), key=lambda x: x[0])
        if side[0] >= best_s * 0.98 and side[0] > scores[0] * 1.05:
            best_deg, best_s = side[1], side[0]
            second_s = scores[0]
        else:
            return 0

    if second_s <= 0:
        return best_deg

    margin = (best_s - second_s) / max(second_s, 1e-6)
    thresh = 0.03 if aggressive else 0.10

    # Near-tie between 90 and 270: pick stronger top/bottom separation
    if {best_deg, second_deg} <= {90, 270} and margin < 0.08:
        def asym(d: int) -> float:
            a = rotated[d]
            h = a.shape[0]
            top = float(a[: h // 4, :].mean())
            bot = float(a[3 * h // 4 :, :].mean())
            return abs(top - bot)

        best_deg = 90 if asym(90) >= asym(270) else 270
        return best_deg

    if margin < thresh:
        # Aggressive: if best clearly beats upright (0), still apply
        if aggressive and best_deg != 0 and best_s > scores[0] * 1.08:
            return best_deg
        return 0
    return best_deg


def _save_image(im: Image.Image, dest: Path, source_ext: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = source_ext.lower()
    rgb = im
    if rgb.mode not in ("RGB", "L", "RGBA"):
        rgb = rgb.convert("RGB")

    if ext in _JPEG_EXTS:
        if rgb.mode == "RGBA":
            bg = Image.new("RGB", rgb.size, (0, 0, 0))
            bg.paste(rgb, mask=rgb.split()[-1])
            rgb = bg
        elif rgb.mode == "L":
            rgb = rgb.convert("RGB")
        # Fresh EXIF with Orientation=1 (drop stale orientation)
        exif = Image.Exif()
        exif[_ORIENT_TAG] = 1
        rgb.save(
            dest,
            "JPEG",
            quality=95,
            optimize=True,
            progressive=True,
            exif=exif,
        )
    elif ext in _PNG_EXTS:
        rgb.save(dest, "PNG", optimize=True)
    elif ext == ".webp":
        rgb.save(dest, "WEBP", quality=95, method=4)
    elif ext in {".tif", ".tiff"}:
        rgb.save(dest, "TIFF")
    else:
        if rgb.mode not in ("RGB", "L"):
            rgb = rgb.convert("RGB")
        rgb.save(dest, "JPEG", quality=95, optimize=True)


def _atomic_replace(tmp: Path, target: Path) -> None:
    tmp.replace(target)


def auto_orient_image(
    path: Path,
    *,
    force_content: bool = False,
    content_fallback: bool = True,
    aggressive: bool = False,
) -> OrientResult:
    """Bake EXIF orientation into pixels; optional content upright when EXIF missing.

    ``force_content`` / ``aggressive``: used for user-triggered batch auto-rotate
    when camera wrote Orientation=1 but pixels are still sideways.
    """
    path = Path(path)
    if not path.is_file():
        return OrientResult(False, None, 1, None, None, 0, "none", str(path))

    ext = path.suffix.lower()
    if ext not in _REWRITE_EXTS:
        orient = read_exif_orientation(path)
        return OrientResult(
            False,
            orient,
            orient or 1,
            None,
            None,
            0,
            "none",
            str(path),
        )

    try:
        with Image.open(path) as im:
            im.load()
            orient_before = None
            try:
                exif = im.getexif()
                if exif and _ORIENT_TAG in exif:
                    orient_before = int(exif[_ORIENT_TAG])
            except Exception:  # noqa: BLE001
                orient_before = None

            method = "none"
            degrees = 0
            working = im

            # Step 1: EXIF bake when tag is non-upright
            if orient_before is not None and orient_before != 1:
                transposed = ImageOps.exif_transpose(im)
                if transposed is not None:
                    working = transposed
                    degrees = _orientation_to_degrees(orient_before)
                    method = "exif"
            elif content_fallback or force_content or aggressive:
                # Step 2: content heuristic (user auto-rotate → aggressive)
                hint = _content_upright_degrees(
                    im, aggressive=aggressive or force_content
                )
                if hint:
                    working = _apply_manual_rotate(im, hint)
                    degrees = hint
                    method = "content"

            if method == "none":
                w, h = im.size
                return OrientResult(
                    False,
                    orient_before,
                    orient_before or 1,
                    w,
                    h,
                    0,
                    "none",
                    str(path),
                )

            working = working.copy()
            w, h = working.size

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=ext or ".jpg",
                dir=str(path.parent),
            ) as tf:
                tmp = Path(tf.name)
            try:
                _save_image(working, tmp, ext)
                _atomic_replace(tmp, path)
            except Exception:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                raise

            log.info(
                "auto_orient",
                path=str(path),
                method=method,
                orient_before=orient_before,
                degrees=degrees,
                size=f"{w}x{h}",
                aggressive=aggressive or force_content,
            )
            return OrientResult(
                True,
                orient_before,
                1,
                w,
                h,
                degrees,
                method,
                str(path),
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.warning("auto_orient_failed", path=str(path), error=str(exc))
        return OrientResult(False, None, 1, None, None, 0, "none", str(path))


def rotate_image(path: Path, degrees_cw: int) -> OrientResult:
    """Manually rotate image clockwise by 90/180/270 and bake Orientation=1."""
    path = Path(path)
    degrees_cw = int(degrees_cw) % 360
    if degrees_cw not in (90, 180, 270):
        raise ValueError("degrees_cw must be 90, 180, or 270")
    if not path.is_file():
        raise FileNotFoundError(str(path))

    ext = path.suffix.lower()
    if ext not in _REWRITE_EXTS:
        raise ValueError(f"Cannot rewrite format {ext}")

    with Image.open(path) as im:
        im.load()
        base = ImageOps.exif_transpose(im) or im
        orient_before = read_exif_orientation(path)
        rotated = _apply_manual_rotate(base, degrees_cw).copy()
        w, h = rotated.size

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=ext or ".jpg",
            dir=str(path.parent),
        ) as tf:
            tmp = Path(tf.name)
        try:
            _save_image(rotated, tmp, ext)
            _atomic_replace(tmp, path)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    log.info("manual_rotate", path=str(path), degrees=degrees_cw, size=f"{w}x{h}")
    return OrientResult(True, orient_before, 1, w, h, degrees_cw, "manual", str(path))
