"""Thumbnail, preview, and video keyframe generation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from neuraldisc.config import Settings, get_settings
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


def ensure_jpeg_rgb(im: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", im.size, (10, 10, 11))
        if im.mode == "P":
            im = im.convert("RGBA")
        background.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
        return background
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def generate_still_derivatives(
    source: Path,
    media_id: str,
    settings: Settings | None = None,
) -> tuple[Path | None, Path | None]:
    settings = settings or get_settings()
    thumb_path = settings.thumbs_dir / f"{media_id}.jpg"
    preview_path = settings.previews_dir / f"{media_id}.jpg"
    try:
        # Drop stale derivatives so rotate always rewrites on disk
        for p in (thumb_path, preview_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        with Image.open(source) as im:
            im = ensure_jpeg_rgb(im)
            _save_resized(im, thumb_path, settings.thumb_size, quality=82)
            _save_resized(im, preview_path, settings.preview_size, quality=88)
        return thumb_path, preview_path
    except Exception as exc:  # noqa: BLE001
        log.warning("derivative_failed", path=str(source), error=str(exc))
        return None, None


def _save_resized(im: Image.Image, dest: Path, max_edge: int, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    clone = im.copy()
    clone.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    # Atomic replace so concurrent readers never see a half-written thumb
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    clone.save(tmp, "JPEG", quality=quality, optimize=True, progressive=True)
    tmp.replace(dest)


def generate_video_derivatives(
    source: Path,
    media_id: str,
    settings: Settings | None = None,
    max_keyframes: int = 8,
) -> tuple[Path | None, Path | None, list[Path]]:
    """Extract poster thumb/preview + keyframes via ffmpeg."""
    settings = settings or get_settings()
    thumb_path = settings.thumbs_dir / f"{media_id}.jpg"
    preview_path = settings.previews_dir / f"{media_id}.jpg"
    kf_dir = settings.keyframes_dir / media_id
    kf_dir.mkdir(parents=True, exist_ok=True)
    keyframes: list[Path] = []

    try:
        # Poster frame at 1s (or 0)
        for dest, scale in ((thumb_path, settings.thumb_size), (preview_path, settings.preview_size)):
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "1",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale='min({scale},iw)':-2",
                    "-q:v",
                    "3",
                    str(dest),
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        # Scene-ish sampling: fps ~1/N over duration is complex; fixed interval
        pattern = str(kf_dir / "kf_%03d.jpg")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"fps=1/{max(1, max_keyframes)},scale='min(800,iw)':-2",
                "-frames:v",
                str(max_keyframes),
                "-q:v",
                "4",
                pattern,
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
        keyframes = sorted(kf_dir.glob("kf_*.jpg"))
    except FileNotFoundError:
        log.warning("ffmpeg_not_found")
    except Exception as exc:  # noqa: BLE001
        log.warning("video_derivative_failed", path=str(source), error=str(exc))

    return (
        thumb_path if thumb_path.exists() else None,
        preview_path if preview_path.exists() else None,
        keyframes,
    )
