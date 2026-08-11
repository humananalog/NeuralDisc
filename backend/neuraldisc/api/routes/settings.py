"""Application settings — library root and quality gates."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neuraldisc import __version__
from neuraldisc.config import Settings, apply_settings_update, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Disc, MediaItem
from neuraldisc.ingest.detector import list_mounted_volumes
from neuraldisc.prefs import prefs_path
from neuraldisc.utils.logging import get_logger

router = APIRouter(prefix="/api/settings", tags=["settings"])
log = get_logger(__name__)


class SettingsOut(BaseModel):
    version: str
    prefs_file: str
    library_root: str
    library_exists: bool
    library_writable: bool
    sqlite_path: str
    db_exists: bool
    originals_dir: str
    staging_dir: str
    quarantine_dir: str
    derivatives_dir: str
    free_bytes: int | None = None
    total_bytes: int | None = None
    media_count: int = 0
    disc_count: int = 0
    # True when staging/temp is under library_root (always required)
    temp_on_target: bool = True

    # Quality
    quality_enabled: bool
    quality_min_short_edge: int
    quality_min_long_edge: int
    quality_min_megapixels: float
    quality_min_image_bytes: int
    quality_min_web_format_bytes: int
    quality_min_video_bytes: int
    quality_min_video_short_edge: int
    quality_max_aspect_ratio: float
    quality_reject_animated_gif: bool
    quality_reject_junk_paths: bool
    quality_quarantine_rejects: bool

    # AI
    vlm_enabled: bool
    embeddings_enabled: bool

    thumb_size: int
    preview_size: int

    # Tooling
    exiftool_ok: bool = False
    exiftool_version: str | None = None
    exiftool_path: str | None = None

    # Secrets (status only — never raw values)
    secrets: dict[str, dict] = Field(default_factory=dict)
    secrets_secure: bool = True


class SettingsUpdate(BaseModel):
    library_root: str | None = None
    quality_enabled: bool | None = None
    quality_min_short_edge: int | None = Field(default=None, ge=64, le=4000)
    quality_min_long_edge: int | None = Field(default=None, ge=64, le=8000)
    quality_min_megapixels: float | None = Field(default=None, ge=0.01, le=50.0)
    quality_min_image_bytes: int | None = Field(default=None, ge=0)
    quality_min_web_format_bytes: int | None = Field(default=None, ge=0)
    quality_min_video_bytes: int | None = Field(default=None, ge=0)
    quality_min_video_short_edge: int | None = Field(default=None, ge=64, le=4000)
    quality_max_aspect_ratio: float | None = Field(default=None, ge=1.0, le=20.0)
    quality_reject_animated_gif: bool | None = None
    quality_reject_junk_paths: bool | None = None
    quality_quarantine_rejects: bool | None = None
    vlm_enabled: bool | None = None
    embeddings_enabled: bool | None = None
    thumb_size: int | None = Field(default=None, ge=64, le=2000)
    preview_size: int | None = Field(default=None, ge=256, le=4000)
    create_if_missing: bool = True


class SecretUpdate(BaseModel):
    """Write or clear a secret. Empty string clears."""

    key: str  # huggingface_token | openai_api_key | generic_api_key
    value: str | None = None


class SecretsStatusOut(BaseModel):
    secrets: dict[str, dict]
    secrets_secure: bool
    secrets_dir: str


class PathCheckRequest(BaseModel):
    path: str
    create_if_missing: bool = False


class PathCheckResponse(BaseModel):
    path: str
    exists: bool
    is_dir: bool
    writable: bool
    free_bytes: int | None = None
    total_bytes: int | None = None
    message: str
    ok: bool


class VolumeSuggestion(BaseModel):
    path: str
    name: str
    is_optical: bool
    is_ejectable: bool


def _disk_usage(path: Path) -> tuple[int | None, int | None]:
    try:
        target = path if path.exists() else path.parent
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
        return usage.free, usage.total
    except OSError:
        return None, None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _writable(path: Path) -> bool:
    try:
        if path.exists():
            return os.access(path, os.W_OK)
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return parent.exists() and os.access(parent, os.W_OK)
    except OSError:
        return False


def _settings_out(s: Settings) -> SettingsOut:
    from neuraldisc.processing.metadata import (
        exiftool_available,
        exiftool_version,
        find_exiftool,
    )

    root = s.library_root
    free, total = _disk_usage(root)
    media_count = disc_count = 0
    try:
        with session_scope() as session:
            media_count = session.query(MediaItem).count()
            disc_count = session.query(Disc).count()
    except Exception:  # noqa: BLE001
        pass

    et_ok = exiftool_available()
    et_path = None
    if et_ok:
        try:
            et_path = find_exiftool()
        except Exception:  # noqa: BLE001
            et_ok = False

    return SettingsOut(
        version=__version__,
        prefs_file=str(prefs_path()),
        library_root=str(root),
        library_exists=root.exists(),
        library_writable=_writable(root),
        sqlite_path=str(s.sqlite_path),
        db_exists=s.sqlite_path.exists(),
        originals_dir=str(s.originals_dir),
        staging_dir=str(s.staging_dir),
        quarantine_dir=str(s.quarantine_dir),
        derivatives_dir=str(s.library_root / "library" / "derivatives"),
        free_bytes=free,
        total_bytes=total,
        media_count=media_count,
        disc_count=disc_count,
        temp_on_target=_is_under(s.staging_dir, root),
        quality_enabled=s.quality_enabled,
        quality_min_short_edge=s.quality_min_short_edge,
        quality_min_long_edge=s.quality_min_long_edge,
        quality_min_megapixels=s.quality_min_megapixels,
        quality_min_image_bytes=s.quality_min_image_bytes,
        quality_min_web_format_bytes=s.quality_min_web_format_bytes,
        quality_min_video_bytes=s.quality_min_video_bytes,
        quality_min_video_short_edge=s.quality_min_video_short_edge,
        quality_max_aspect_ratio=s.quality_max_aspect_ratio,
        quality_reject_animated_gif=s.quality_reject_animated_gif,
        quality_reject_junk_paths=s.quality_reject_junk_paths,
        quality_quarantine_rejects=s.quality_quarantine_rejects,
        vlm_enabled=s.vlm_enabled,
        embeddings_enabled=s.embeddings_enabled,
        thumb_size=s.thumb_size,
        preview_size=s.preview_size,
        exiftool_ok=et_ok,
        exiftool_version=exiftool_version() if et_ok else None,
        exiftool_path=et_path,
        secrets=_secret_status(),
        secrets_secure=_secrets_secure(),
    )


def _secret_status() -> dict:
    from neuraldisc.secrets_store import list_secret_status

    return list_secret_status()


def _secrets_secure() -> bool:
    from neuraldisc.secrets_store import secrets_file_secure

    return secrets_file_secure()


@router.get("", response_model=SettingsOut)
def get_app_settings() -> SettingsOut:
    return _settings_out(get_settings())


@router.get("/secrets", response_model=SecretsStatusOut)
def get_secrets_status() -> SecretsStatusOut:
    from neuraldisc.secrets_store import APP_DIR, list_secret_status, secrets_file_secure

    return SecretsStatusOut(
        secrets=list_secret_status(),
        secrets_secure=secrets_file_secure(),
        secrets_dir=str(APP_DIR),
    )


@router.put("/secrets", response_model=SecretsStatusOut)
def put_secret(body: SecretUpdate) -> SecretsStatusOut:
    """Store a secret encrypted at rest. Never logged or returned in full."""
    from neuraldisc.secrets_store import (
        APP_DIR,
        SECRET_KEYS,
        list_secret_status,
        secrets_file_secure,
        set_secret,
    )

    if body.key not in SECRET_KEYS:
        raise HTTPException(400, f"Unknown secret key. Allowed: {sorted(SECRET_KEYS)}")
    # Reject if client accidentally sent a masked value back
    val = body.value
    if val is not None and "…" in val:
        raise HTTPException(400, "Masked value rejected — paste the full token")
    try:
        set_secret(body.key, val)
    except Exception as exc:  # noqa: BLE001
        log.exception("secret_store_failed")
        raise HTTPException(500, "Failed to store secret") from exc
    log.info("secret_updated", key=body.key, configured=bool(val and val.strip()))
    return SecretsStatusOut(
        secrets=list_secret_status(),
        secrets_secure=secrets_file_secure(),
        secrets_dir=str(APP_DIR),
    )


@router.delete("/secrets/{key}", response_model=SecretsStatusOut)
def delete_secret(key: str) -> SecretsStatusOut:
    from neuraldisc.secrets_store import (
        APP_DIR,
        SECRET_KEYS,
        list_secret_status,
        secrets_file_secure,
        set_secret,
    )

    if key not in SECRET_KEYS:
        raise HTTPException(400, f"Unknown secret key. Allowed: {sorted(SECRET_KEYS)}")
    set_secret(key, None)
    log.info("secret_deleted", key=key)
    return SecretsStatusOut(
        secrets=list_secret_status(),
        secrets_secure=secrets_file_secure(),
        secrets_dir=str(APP_DIR),
    )


@router.patch("", response_model=SettingsOut)
def update_app_settings(body: SettingsUpdate) -> SettingsOut:
    data = body.model_dump(exclude_unset=True)
    create = data.pop("create_if_missing", True)

    if "library_root" in data and data["library_root"]:
        root = Path(data["library_root"]).expanduser()
        if not root.is_absolute():
            raise HTTPException(400, "Library path must be absolute (e.g. /Volumes/SSD/NeuralDisc)")
        if root.exists() and not root.is_dir():
            raise HTTPException(400, f"Path exists but is not a directory: {root}")
        if not root.exists():
            if not create:
                raise HTTPException(400, f"Path does not exist: {root}")
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HTTPException(400, f"Cannot create directory: {exc}") from exc
        if not _writable(root):
            raise HTTPException(400, f"Path is not writable: {root}")
        data["library_root"] = str(root)

    if not data:
        return _settings_out(get_settings())

    try:
        settings = apply_settings_update(data)
    except Exception as exc:  # noqa: BLE001
        log.exception("settings_update_failed")
        raise HTTPException(500, str(exc)) from exc

    log.info("settings_updated", keys=list(data.keys()), library=str(settings.library_root))
    return _settings_out(settings)


@router.post("/check-path", response_model=PathCheckResponse)
def check_path(body: PathCheckRequest) -> PathCheckResponse:
    path = Path(body.path).expanduser()
    if not path.is_absolute():
        return PathCheckResponse(
            path=str(path),
            exists=False,
            is_dir=False,
            writable=False,
            message="Path must be absolute",
            ok=False,
        )
    exists = path.exists()
    is_dir = path.is_dir() if exists else False
    if not exists and body.create_if_missing:
        try:
            path.mkdir(parents=True, exist_ok=True)
            exists = True
            is_dir = True
        except OSError as exc:
            return PathCheckResponse(
                path=str(path),
                exists=False,
                is_dir=False,
                writable=False,
                message=f"Cannot create: {exc}",
                ok=False,
            )
    writable = _writable(path)
    free, total = _disk_usage(path)
    ok = exists and is_dir and writable
    if ok:
        msg = "Ready — writable library location"
    elif not exists:
        msg = "Does not exist"
    elif not is_dir:
        msg = "Not a directory"
    else:
        msg = "Not writable"
    return PathCheckResponse(
        path=str(path),
        exists=exists,
        is_dir=is_dir,
        writable=writable,
        free_bytes=free,
        total_bytes=total,
        message=msg,
        ok=ok,
    )


@router.get("/volumes", response_model=list[VolumeSuggestion])
def volume_suggestions() -> list[VolumeSuggestion]:
    out: list[VolumeSuggestion] = []
    try:
        for v in list_mounted_volumes():
            # Suggest NeuralDisc subfolder on external volumes
            out.append(
                VolumeSuggestion(
                    path=str(v.path / "NeuralDisc"),
                    name=f"{v.name} → NeuralDisc",
                    is_optical=v.is_optical,
                    is_ejectable=v.is_ejectable,
                )
            )
            out.append(
                VolumeSuggestion(
                    path=str(v.path),
                    name=v.name,
                    is_optical=v.is_optical,
                    is_ejectable=v.is_ejectable,
                )
            )
    except Exception:  # noqa: BLE001
        pass
    # Common defaults
    home = Path.home() / "NeuralDisc"
    out.insert(
        0,
        VolumeSuggestion(
            path=str(home),
            name="Home → NeuralDisc",
            is_optical=False,
            is_ejectable=False,
        ),
    )
    return out
