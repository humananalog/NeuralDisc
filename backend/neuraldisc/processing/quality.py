"""Quality gates — reject junk before it enters the library.

Blocks:
  - Vector / non-photographic formats (SVG, EPS, ICO, …)
  - Tiny images (icons, favicons, web thumbnails)
  - Obvious internet-scrap / UI asset path names
  - Animated GIF meme packs, extreme aspect ratios
  - Undersized videos
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from neuraldisc.config import Settings
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# Never accepted as library media (vectors, icons, documents, …)
BLOCKED_EXTENSIONS = frozenset(
    {
        ".svg",
        ".svgz",
        ".eps",
        ".ai",
        ".pdf",
        ".emf",
        ".wmf",
        ".ico",
        ".icns",
        ".cur",
        ".ani",
        ".xcf",  # GIMP project
        ".psd",  # often multi-layer work files, not archive photos
        ".sketch",
        ".fig",
        ".cdr",
        ".swf",
        ".tga",  # rarely camera original; often game/web assets
    }
)

# Allowed by extension list but treated as high-risk web formats
WEBBY_EXTENSIONS = frozenset({".gif", ".webp", ".bmp", ".png"})

# Path / filename signals for downloaded junk, UI chrome, thumbs
_JUNK_PATH_RE = re.compile(
    r"""
    (?:^|[/\\._\-])
    (?:
        thumb(?:nail|s)? |
        favicon |
        icon(?:s)? |
        emoji(?:s)? |
        smiley |
        emoticon(?:s)? |
        avatar(?:s)? |
        sprite(?:s)? |
        logo(?:s)? |
        banner(?:s)? |
        watermark |
        placeholder |
        stock[_-]?preview |
        web[_-]?thumb |
        cache |
        tmp |
        temp |
        download(?:s|ed)? |
        reddit |
        imgur |
        twitter |
        facebook |
        instagram |
        pinterest |
        meme(?:s)? |
        reaction(?:s)? |
        sticker(?:s)? |
        badge(?:s)? |
        button(?:s)? |
        widget(?:s)? |
        skin(?:s)? |
        theme(?:s)? |
        wallpaper[_-]?thumb
    )
    (?:$|[/\\._\-])
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Folder names that almost never hold archive photos
_JUNK_DIR_NAMES = frozenset(
    {
        "thumbs",
        "thumbnails",
        "icons",
        "icon",
        "favicons",
        "emojis",
        "emoji",
        "stickers",
        "sprites",
        "avatars",
        "reactions",
        "memes",
        "gifs",
        "web",
        "www",
        "http",
        "https",
        "downloads",
        "browser",
        "cache",
        "cached",
        "tmp",
        "temp",
        "__macosx",
        ".trash",
        "node_modules",
        "assets",
        "static",
        "public",
        "dist",
        "build",
    }
)


@dataclass(frozen=True)
class QualityVerdict:
    accepted: bool
    reason: str | None = None
    code: str | None = None  # e.g. too_small, vector, junk_path, animated_gif

    @property
    def rejected(self) -> bool:
        return not self.accepted


def reject(code: str, reason: str) -> QualityVerdict:
    return QualityVerdict(accepted=False, reason=reason, code=code)


def accept() -> QualityVerdict:
    return QualityVerdict(accepted=True)


def evaluate_path(path: Path, settings: Settings) -> QualityVerdict:
    """Cheap pre-copy checks (extension, size, path heuristics)."""
    ext = path.suffix.lower()

    if ext in BLOCKED_EXTENSIONS:
        return reject("vector_or_blocked", f"Blocked format {ext}")

    if not path.is_file():
        return reject("not_a_file", "Not a regular file")

    try:
        size = path.stat().st_size
    except OSError as exc:
        return reject("unreadable", str(exc))

    # Prove the bytes are readable (stat can succeed on some mounts while open fails)
    try:
        with path.open("rb") as f:
            f.read(1)
    except OSError as exc:
        return reject("unreadable", str(exc) or "cannot open for reading")

    # Absolute floor — empty / truncated trash
    if size <= 0:
        return reject("empty", "Empty file")
    if size < 2048:
        return reject("file_too_small", f"File size {size} B is trivially small")

    # Filename / path junk signals (web scrapes, UI packs)
    if settings.quality_reject_junk_paths:
        full = str(path).replace("\\", "/")
        name = path.name
        if _JUNK_PATH_RE.search(name) or _JUNK_PATH_RE.search(full):
            return reject("junk_path", f"Path looks like web/UI junk: {name}")
        for part in path.parts:
            if part.lower() in _JUNK_DIR_NAMES:
                return reject("junk_dir", f"Directory suggests non-archive media: {part}")

    is_video = ext in {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
        ".wmv",
        ".mpg",
        ".mpeg",
        ".3gp",
    }

    if is_video:
        if size < settings.quality_min_video_bytes:
            return reject(
                "file_too_small",
                f"Video size {size} B below minimum {settings.quality_min_video_bytes} B",
            )
        return accept()

    # Fast image header probe — dimension gates beat raw byte size
    # (solid-colour test fixtures can be large in pixels but small on disk)
    dim: tuple[int, int] | None = None
    if ext in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }:
        dim = _probe_image_dimensions(path)
        if dim is not None:
            w, h = dim
            v = evaluate_dimensions(w, h, settings, media_type="image")
            if v.rejected:
                return v
        if ext == ".gif":
            anim = _is_animated_gif(path)
            if anim and settings.quality_reject_animated_gif:
                return reject("animated_gif", "Animated GIF (likely web meme/reaction)")

    # Byte-size floor when dimensions are unknown or only barely acceptable
    dims_ok_strong = False
    if dim is not None:
        short_edge = min(dim)
        dims_ok_strong = short_edge >= settings.quality_min_short_edge * 1.25

    if not dims_ok_strong:
        min_bytes = settings.quality_min_image_bytes
        if ext in WEBBY_EXTENSIONS:
            min_bytes = settings.quality_min_web_format_bytes
        if size < min_bytes:
            return reject(
                "file_too_small",
                f"File size {size} B below minimum {min_bytes} B "
                f"(and dimensions not strongly above minimum)",
            )

    # Web formats that pass dims still need a modest size (often empty PNG shells)
    if ext in WEBBY_EXTENSIONS and size < max(8192, settings.quality_min_web_format_bytes // 4):
        return reject(
            "web_format_too_small",
            f"Web format {ext} size {size} B is suspiciously small",
        )

    return accept()


def evaluate_dimensions(
    width: int | None,
    height: int | None,
    settings: Settings,
    media_type: str = "image",
) -> QualityVerdict:
    if width is None or height is None or width <= 0 or height <= 0:
        # Unknown dims — allow through for RAW/HEIC until decoder runs; video handled later
        if media_type == "image":
            return accept()
        return accept()

    short_edge = min(width, height)
    long_edge = max(width, height)
    megapixels = (width * height) / 1_000_000.0

    if media_type == "video":
        if short_edge < settings.quality_min_video_short_edge:
            return reject(
                "video_too_small",
                f"Video {width}×{height} short edge < {settings.quality_min_video_short_edge}px",
            )
        return accept()

    if short_edge < settings.quality_min_short_edge:
        return reject(
            "too_small",
            f"{width}×{height} short edge {short_edge}px < {settings.quality_min_short_edge}px",
        )
    if long_edge < settings.quality_min_long_edge:
        return reject(
            "too_small",
            f"{width}×{height} long edge {long_edge}px < {settings.quality_min_long_edge}px",
        )
    if megapixels < settings.quality_min_megapixels:
        return reject(
            "too_small",
            f"{megapixels:.3f} MP < {settings.quality_min_megapixels} MP minimum",
        )

    # Extreme aspect ratios = banners / strips / UI chrome, not photos
    ratio = long_edge / max(short_edge, 1)
    if ratio > settings.quality_max_aspect_ratio:
        return reject(
            "extreme_aspect",
            f"Aspect ratio {ratio:.1f}:1 exceeds max {settings.quality_max_aspect_ratio}:1",
        )

    return accept()


def evaluate_media_item(
    path: Path,
    *,
    media_type: str,
    width: int | None,
    height: int | None,
    file_size: int | None,
    settings: Settings,
) -> QualityVerdict:
    """Full post-metadata gate used by the processing pipeline."""
    # Path/extension/junk first (skip re-probing via evaluate_path when we have dims)
    ext = path.suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return reject("vector_or_blocked", f"Blocked format {ext}")

    if settings.quality_reject_junk_paths:
        name = path.name
        full = str(path).replace("\\", "/")
        if _JUNK_PATH_RE.search(name) or _JUNK_PATH_RE.search(full):
            return reject("junk_path", f"Path looks like web/UI junk: {name}")
        for part in path.parts:
            if part.lower() in _JUNK_DIR_NAMES:
                return reject("junk_dir", f"Directory suggests non-archive media: {part}")

    dim = evaluate_dimensions(width, height, settings, media_type=media_type)
    if dim.rejected:
        return dim

    if file_size is not None and file_size < 2048:
        return reject("file_too_small", f"File size {file_size} B is trivially small")

    if media_type == "video":
        if file_size is not None and file_size < settings.quality_min_video_bytes:
            return reject(
                "file_too_small",
                f"Video size {file_size} B < {settings.quality_min_video_bytes} B",
            )
        return accept()

    # Images: enforce byte floor only when resolution is weak/unknown
    dims_ok_strong = (
        width is not None
        and height is not None
        and min(width, height) >= settings.quality_min_short_edge * 1.25
    )
    if file_size is not None and not dims_ok_strong:
        min_bytes = settings.quality_min_image_bytes
        if ext in WEBBY_EXTENSIONS:
            min_bytes = settings.quality_min_web_format_bytes
        if file_size < min_bytes:
            return reject("file_too_small", f"File size {file_size} B < {min_bytes} B")

    if ext == ".gif" and settings.quality_reject_animated_gif and _is_animated_gif(path):
        return reject("animated_gif", "Animated GIF (likely web meme/reaction)")

    return accept()


def _probe_image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            return im.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _is_animated_gif(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            n = getattr(im, "n_frames", 1) or 1
            return n > 1
    except (UnidentifiedImageError, OSError, ValueError):
        return False
