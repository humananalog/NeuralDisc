"""ORM → API schema helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from neuraldisc.api.schemas import AnalysisOut, MediaOut
from neuraldisc.config import Settings, get_settings
from neuraldisc.db.models import MediaAnalysis, MediaItem


def _media_asset_version(media: MediaItem, asset_path: Path | None = None) -> str:
    """Cache-bust token so browsers reload thumbs after rotate/rewrite.

    Combines updated_at, rotation, sha256 prefix, and derivative mtime when present.
    """
    parts: list[str] = []
    ua = getattr(media, "updated_at", None)
    if isinstance(ua, datetime):
        parts.append(str(int(ua.timestamp() * 1000)))
    rot = int(getattr(media, "rotation_degrees", 0) or 0)
    parts.append(f"r{rot}")
    sha = (media.sha256 or "")[:12]
    if sha:
        parts.append(sha)
    if asset_path is not None:
        try:
            if asset_path.is_file():
                parts.append(str(int(asset_path.stat().st_mtime_ns)))
        except OSError:
            pass
    return "-".join(parts) if parts else "0"


def media_to_out(media: MediaItem, settings: Settings | None = None) -> MediaOut:
    settings = settings or get_settings()
    analysis = None
    if media.analysis:
        analysis = analysis_to_out(media.analysis)

    thumb = settings.thumbs_dir / f"{media.id}.jpg"
    preview = settings.previews_dir / f"{media.id}.jpg"
    thumb_v = _media_asset_version(media, thumb if thumb.exists() else None)
    preview_v = _media_asset_version(media, preview if preview.exists() else None)

    return MediaOut(
        id=media.id,
        disc_id=media.disc_id,
        filename=media.filename,
        media_type=media.media_type,
        mime_type=media.mime_type,
        file_size=media.file_size,
        width=media.width,
        height=media.height,
        duration_ms=media.duration_ms,
        sha256=media.sha256,
        phash=media.phash,
        taken_at=media.taken_at,
        camera_make=media.camera_make,
        camera_model=media.camera_model,
        gps_lat=media.gps_lat,
        gps_lon=media.gps_lon,
        orientation=media.orientation,
        quality_score=media.quality_score,
        blur_score=media.blur_score,
        is_blurry=bool(media.is_blurry),
        is_duplicate=media.is_duplicate,
        best_of_group=media.best_of_group,
        hitl_status=media.hitl_status,
        lifecycle=media.lifecycle or "library",
        deleted_at=getattr(media, "deleted_at", None),
        auto_rotated=bool(getattr(media, "auto_rotated", False)),
        rotation_degrees=int(getattr(media, "rotation_degrees", 0) or 0),
        rating=media.rating or 0,
        flag=bool(media.flag),
        colour_label=media.colour_label,
        library_path=media.library_path,
        original_path=media.original_path,
        created_at=media.created_at,
        updated_at=media.updated_at,
        # Version query forces immediate thumb refresh after rotate
        thumb_url=f"/api/media/{media.id}/thumb?v={thumb_v}" if thumb.exists() else None,
        preview_url=(
            f"/api/media/{media.id}/preview?v={preview_v}" if preview.exists() else None
        ),
        original_url=f"/api/media/{media.id}/original?v={thumb_v}",
        analysis=analysis,
    )


def analysis_to_out(a: MediaAnalysis) -> AnalysisOut:
    return AnalysisOut(
        caption_short=a.caption_short,
        description=a.description,
        scene_type=a.scene_type,
        people_count=a.people_count,
        people_desc=a.people_desc,
        objects=_loads_list(a.objects),
        suggested_tags=_loads_list(a.suggested_tags),
        estimated_era=a.estimated_era,
        confidence=a.confidence,
        model_name=a.model_name,
        model_version=a.model_version,
        analysed_at=a.analysed_at,
        human_edited=bool(a.human_edited),
    )


def _loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []
