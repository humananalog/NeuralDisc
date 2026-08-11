"""Application configuration.

Library root defaults to ~/NeuralDisc for local development.
Override via NEURALDISC_LIBRARY_ROOT or config/settings.toml.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Supported media extensions (lowercase) — archive photography / video first.
# Vectors, icons, and UI formats are intentionally excluded (see quality.BLOCKED_EXTENSIONS).
IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".png",
        ".heic",
        ".heif",
        ".raw",
        ".cr2",
        ".nef",
        ".arw",
        ".dng",
        # Web-ish formats allowed only if quality gates pass (size / dimensions)
        ".gif",
        ".webp",
        ".bmp",
    }
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".mpg", ".mpeg", ".3gp"}
)
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEURALDISC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    library_root: Path = Field(
        default_factory=lambda: Path.home() / "NeuralDisc",
        description="Root of the NeuralDisc library tree",
    )

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3020",
            "http://127.0.0.1:3020",
            "http://localhost:3010",
            "http://127.0.0.1:3010",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # Processing
    thumb_size: int = 400
    preview_size: int = 1600
    phash_threshold: int = 8
    embedding_similarity_threshold: float = 0.92
    low_confidence_threshold: float = 0.55

    # Quality gates — reject junk before library entry (override via NEURALDISC_QUALITY_*)
    quality_enabled: bool = True
    quality_min_short_edge: int = 480  # px — kill icons / favicons / tiny web thumbs
    quality_min_long_edge: int = 640
    quality_min_megapixels: float = 0.35  # ~640×560
    quality_min_image_bytes: int = 25_000  # 25 KB
    quality_min_web_format_bytes: int = 40_000  # gif/webp/bmp/png bar higher
    quality_min_video_bytes: int = 200_000  # 200 KB
    quality_min_video_short_edge: int = 360  # reject postage-stamp clips
    quality_max_aspect_ratio: float = 3.5  # reject extreme banners/strips
    quality_reject_animated_gif: bool = True
    quality_reject_junk_paths: bool = True
    # If True, quarantine rejected files under library/quarantine; else leave on disc only
    quality_quarantine_rejects: bool = True

    # Blur detection (Laplacian variance — lower = blurrier)
    blur_enabled: bool = True
    blur_threshold: float = 80.0  # below this ⇒ is_blurry
    blur_auto_flag: bool = True  # set media.flag when blurry
    blur_hitl_priority: int = 15  # HITL priority boost (lower number = higher priority)

    # Auto-rotate: bake EXIF Orientation + optional content upright heuristic
    auto_rotate_enabled: bool = True
    auto_rotate_content_fallback: bool = True  # when EXIF missing / Orientation=1

    # AI (optional)
    # Prefer compact VL model for throughput; override via NEURALDISC_VLM_MODEL
    vlm_model: str = "mlx-community/Qwen3-VL-2B-Instruct-4bit"
    embedding_model: str = "clip-vit-base-patch32"
    vlm_enabled: bool = False
    embeddings_enabled: bool = False

    # Jobs
    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = False
    max_workers: int = 2

    # Ingest / high-throughput import
    volumes_path: Path = Path("/Volumes")
    watch_volumes: bool = False
    auto_eject: bool = False
    # Parallelism: copy is I/O-bound; process (EXIF/VLM) is separate
    import_copy_workers: int = 6
    import_process_workers: int = 2
    # Keep files in staging until fully processed & classified, then promote
    import_stage_until_classified: bool = True
    # SOTA pipeline: copy-only to staging (temp) so discs can rotate immediately.
    # Classification / VLM / promote run on a global background worker and never
    # block the next disc copy.
    import_copy_only: bool = True
    # One disc/source import at a time for optical rotation (queue is serial).
    import_copy_serial: bool = True
    # How many staging rows the background processor claims per batch
    import_process_claim: int = 16
    # Expand zip/tar/… on disc when they contain photos/videos
    import_expand_archives: bool = True
    # Safety caps for malicious / huge archives (zip bombs)
    import_archive_max_files: int = 50_000
    import_archive_max_bytes: int = 8 * 1024 * 1024 * 1024  # 8 GiB total extract

    # Auto-resume supervisor — no unfinished work left idle after restarts
    auto_resume_enabled: bool = True
    auto_resume_interval_sec: int = 30
    auto_resume_imports: bool = True
    auto_resume_inference: bool = True  # when VLM enabled + library queue non-empty
    auto_resume_inference_limit: int = 50

    @property
    def library(self) -> Path:
        return self.library_root

    @property
    def originals_dir(self) -> Path:
        return self.library_root / "library" / "originals" / "by-provenance"

    @property
    def organised_dir(self) -> Path:
        return self.library_root / "library" / "organised"

    @property
    def thumbs_dir(self) -> Path:
        return self.library_root / "library" / "derivatives" / "thumbs"

    @property
    def previews_dir(self) -> Path:
        return self.library_root / "library" / "derivatives" / "previews"

    @property
    def keyframes_dir(self) -> Path:
        return self.library_root / "library" / "derivatives" / "keyframes"

    @property
    def staging_dir(self) -> Path:
        """Import temp area — ALWAYS under library_root (target SSD), never /tmp."""
        return self.library_root / "library" / "staging"

    @property
    def temp_dir(self) -> Path:
        """Alias for staging — all transient import files live on the target volume."""
        return self.staging_dir

    @property
    def db_dir(self) -> Path:
        return self.library_root / "db"

    @property
    def sqlite_path(self) -> Path:
        return self.db_dir / "neuraldisc.sqlite"

    @property
    def lancedb_dir(self) -> Path:
        return self.db_dir / "lancedb"

    @property
    def logs_dir(self) -> Path:
        return self.library_root / "logs"

    @property
    def config_dir(self) -> Path:
        return self.library_root / "config"

    @property
    def exports_dir(self) -> Path:
        return self.library_root / "exports"

    @property
    def quarantine_dir(self) -> Path:
        return self.library_root / "library" / "quarantine"

    def ensure_layout(self) -> None:
        """Create the canonical library folder structure on the *target* volume."""
        root = self.library_root.expanduser()
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        dirs = [
            self.originals_dir,
            self.organised_dir,
            self.thumbs_dir,
            self.previews_dir,
            self.keyframes_dir,
            self.staging_dir,
            self.db_dir,
            self.lancedb_dir,
            self.logs_dir / "ingest",
            self.logs_dir / "jobs",
            self.logs_dir / "errors",
            self.config_dir,
            self.exports_dir,
            self.quarantine_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            self.assert_on_target(d, label=str(d.name))

    def assert_on_target(self, path: Path, *, label: str = "path") -> Path:
        """Ensure path resolves under library_root (target SSD), not local /tmp."""
        root = self.library_root.expanduser().resolve()
        p = path.expanduser()
        try:
            p = p.resolve()
        except OSError:
            p = Path(os.path.abspath(os.path.expanduser(str(path))))
        try:
            p.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                f"{label} must be under library target {root}, got {p}. "
                "Set Settings → library folder to your external volume."
            ) from exc
        return p


@lru_cache
def get_settings() -> Settings:
    # Load ~/.neuraldisc/settings.toml into env (env/CLI still wins)
    from neuraldisc.prefs import apply_prefs_to_environ

    apply_prefs_to_environ()
    return Settings()


def reset_settings() -> None:
    """Clear cached settings (for tests)."""
    get_settings.cache_clear()


def apply_library_root(path: str | Path) -> Settings:
    """Override library root, persist prefs, and refresh settings cache."""
    from neuraldisc.prefs import force_environ, save_prefs

    root = str(Path(path).expanduser().resolve())
    force_environ({"library_root": root})
    save_prefs({"library_root": root})
    reset_settings()
    settings = get_settings()
    settings.ensure_layout()
    return settings


def apply_settings_update(updates: dict[str, Any]) -> Settings:
    """Apply a partial settings update from the API, persist, re-bind DB if needed."""
    from neuraldisc.prefs import force_environ, save_prefs
    from neuraldisc.db.database import create_all, init_engine, reset_engine

    cleaned: dict[str, Any] = {}
    for key, value in updates.items():
        if value is None:
            continue
        cleaned[key] = value

    library_changed = False
    if "library_root" in cleaned:
        root = Path(str(cleaned["library_root"])).expanduser()
        cleaned["library_root"] = str(root if root.is_absolute() else root.absolute())
        library_changed = True

    force_environ(cleaned)
    save_prefs(cleaned)
    reset_settings()
    settings = get_settings()
    settings.ensure_layout()

    if library_changed:
        reset_engine()
        init_engine(settings)
        create_all()

    return settings
