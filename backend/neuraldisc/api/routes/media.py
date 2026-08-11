"""Media listing, detail, file serving, delete, and rotate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from neuraldisc.api.schemas import (
    MediaBatchRotateRequest,
    MediaBatchRotateResponse,
    MediaDeleteRequest,
    MediaDeleteResponse,
    MediaListResponse,
    MediaOut,
    MediaRotateRequest,
    MediaRotateResponse,
    MediaUpdateRequest,
)
from neuraldisc.api.serializers import media_to_out
from neuraldisc.config import get_settings
from neuraldisc.db.database import get_db
from neuraldisc.db.fts import search_fts, upsert_fts
from neuraldisc.db.models import MediaAnalysis, MediaItem
from neuraldisc.processing.catalogue import (
    permanent_delete_media,
    restore_media,
    soft_delete_media,
)
from neuraldisc.processing.derivatives import generate_still_derivatives
from neuraldisc.processing.hashes import compute_perceptual_hashes
from neuraldisc.processing.orientation import auto_orient_image, rotate_image
from neuraldisc.utils.hashing import sha256_file
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("", response_model=MediaListResponse)
def list_media(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = None,
    media_type: str | None = None,
    hitl_status: str | None = None,
    is_duplicate: bool | None = None,
    is_blurry: bool | None = None,
    rating_min: int | None = None,
    has_gps: bool | None = None,
    disc_id: str | None = None,
    flag: bool | None = None,
    lifecycle: str | None = None,
    trash: bool = False,
    sort: str = "taken_at_desc",
    db: Session = Depends(get_db),
) -> MediaListResponse:
    query = db.query(MediaItem).options(joinedload(MediaItem.analysis))

    # Catalogue views: library (default) vs trash
    if trash or lifecycle == "trash":
        query = query.filter(MediaItem.lifecycle == "trash")
    elif lifecycle:
        query = query.filter(MediaItem.lifecycle == lifecycle)
    else:
        # Default: only show promoted library items (not staging / rejected / trash)
        query = query.filter(
            (MediaItem.lifecycle == "library") | (MediaItem.lifecycle.is_(None))
        )

    if media_type:
        query = query.filter(MediaItem.media_type == media_type)
    if hitl_status:
        query = query.filter(MediaItem.hitl_status == hitl_status)
    if is_duplicate is not None:
        query = query.filter(MediaItem.is_duplicate == is_duplicate)
    if is_blurry is not None:
        query = query.filter(MediaItem.is_blurry == is_blurry)
    if rating_min is not None:
        query = query.filter(MediaItem.rating >= rating_min)
    if has_gps is True:
        query = query.filter(MediaItem.gps_lat.isnot(None))
    if has_gps is False:
        query = query.filter(MediaItem.gps_lat.is_(None))
    if disc_id:
        query = query.filter(MediaItem.disc_id == disc_id)
    if flag is not None:
        query = query.filter(MediaItem.flag == flag)

    if q and q.strip():
        ids = search_fts(db, q.strip(), limit=500)
        if ids:
            query = query.filter(MediaItem.id.in_(ids))
        else:
            # Filename fallback
            query = query.filter(MediaItem.filename.ilike(f"%{q.strip()}%"))

    total = query.count()

    if sort == "taken_at_asc":
        query = query.order_by(MediaItem.taken_at.asc().nullslast(), MediaItem.created_at.asc())
    elif sort == "created_at_desc":
        query = query.order_by(MediaItem.created_at.desc())
    elif sort == "rating_desc":
        query = query.order_by(MediaItem.rating.desc(), MediaItem.created_at.desc())
    elif sort == "deleted_at_desc":
        query = query.order_by(MediaItem.deleted_at.desc().nullslast())
    else:
        query = query.order_by(MediaItem.taken_at.desc().nullslast(), MediaItem.created_at.desc())

    items = query.offset(offset).limit(limit).all()
    settings = get_settings()
    return MediaListResponse(
        items=[media_to_out(m, settings) for m in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{media_id}", response_model=MediaOut)
def get_media(media_id: str, db: Session = Depends(get_db)) -> MediaOut:
    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")
    return media_to_out(media)


@router.patch("/{media_id}", response_model=MediaOut)
def update_media(
    media_id: str, body: MediaUpdateRequest, db: Session = Depends(get_db)
) -> MediaOut:
    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")

    if body.hitl_status is not None:
        media.hitl_status = body.hitl_status
    if body.rating is not None:
        media.rating = max(0, min(5, body.rating))
    if body.flag is not None:
        media.flag = body.flag
    if body.colour_label is not None:
        media.colour_label = body.colour_label

    analysis = media.analysis
    edited = False
    if body.caption_short is not None or body.description is not None or body.suggested_tags is not None:
        if analysis is None:
            analysis = MediaAnalysis(media_id=media.id)
            db.add(analysis)
        if body.caption_short is not None:
            analysis.caption_short = body.caption_short
            edited = True
        if body.description is not None:
            analysis.description = body.description
            edited = True
        if body.suggested_tags is not None:
            analysis.suggested_tags = json.dumps(body.suggested_tags)
            edited = True
        if edited:
            analysis.human_edited = True
            media.hitl_status = "edited"
        db.flush()
        upsert_fts(db, media, analysis)

    media.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(media)
    return media_to_out(media)


@router.delete("/{media_id}", response_model=MediaDeleteResponse)
def delete_media(
    media_id: str,
    permanent: bool = Query(False, description="If true, permanently purge files + DB row"),
    db: Session = Depends(get_db),
) -> MediaDeleteResponse:
    """Soft-delete (trash) by default; permanent=true purges files and DB."""
    media = db.get(MediaItem, media_id)
    if not media:
        raise HTTPException(404, "Media not found")

    settings = get_settings()
    try:
        if permanent:
            permanent_delete_media(db, media, settings)
            db.commit()
            return MediaDeleteResponse(deleted=[media_id], mode="permanent", count=1)

        soft_delete_media(db, media)
        db.commit()
        return MediaDeleteResponse(trashed=[media_id], mode="trash", count=1)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("delete_media_failed", media_id=media_id)
        raise HTTPException(500, f"Delete failed: {exc}") from exc


@router.post("/batch-delete", response_model=MediaDeleteResponse)
def batch_delete_media(
    body: MediaDeleteRequest,
    db: Session = Depends(get_db),
) -> MediaDeleteResponse:
    """Trash or permanently delete many items (catalogue bulk action)."""
    if not body.ids:
        raise HTTPException(400, "ids required")
    if len(body.ids) > 500:
        raise HTTPException(400, "Max 500 items per batch")

    settings = get_settings()
    deleted: list[str] = []
    trashed: list[str] = []

    try:
        for mid in body.ids:
            media = db.get(MediaItem, mid)
            if not media:
                continue
            if body.permanent:
                permanent_delete_media(db, media, settings)
                deleted.append(mid)
            else:
                soft_delete_media(db, media)
                trashed.append(mid)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("batch_delete_failed")
        raise HTTPException(500, f"Delete failed: {exc}") from exc

    mode = "permanent" if body.permanent else "trash"
    return MediaDeleteResponse(
        deleted=deleted,
        trashed=trashed,
        mode=mode,
        count=len(deleted) + len(trashed),
    )


@router.post("/{media_id}/restore", response_model=MediaOut)
def restore_media_item(media_id: str, db: Session = Depends(get_db)) -> MediaOut:
    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")
    if (media.lifecycle or "") != "trash":
        raise HTTPException(400, "Media is not in trash")
    restore_media(db, media)
    db.commit()
    db.refresh(media)
    return media_to_out(media)


@router.post("/batch-restore", response_model=MediaDeleteResponse)
def batch_restore_media(
    body: MediaDeleteRequest,
    db: Session = Depends(get_db),
) -> MediaDeleteResponse:
    restored: list[str] = []
    for mid in body.ids:
        media = db.get(MediaItem, mid)
        if not media or (media.lifecycle or "") != "trash":
            continue
        restore_media(db, media)
        restored.append(mid)
    db.commit()
    return MediaDeleteResponse(restored=restored, mode="restore", count=len(restored))


def _run_rotate_on_media(
    media: MediaItem,
    mode: str,
    *,
    aggressive: bool = False,
) -> tuple[object, Path]:
    """Apply rotate to file; returns (OrientResult, path). Does not commit DB."""
    if media.media_type != "image":
        raise ValueError("Only images can be rotated")
    path = Path(media.library_path)
    if not path.exists():
        raise FileNotFoundError("Original file missing")

    mode = (mode or "auto").lower().strip()
    if mode == "auto":
        # User-triggered auto always uses aggressive content upright detection
        result = auto_orient_image(
            path,
            content_fallback=True,
            force_content=True,
            aggressive=aggressive or True,
        )
    elif mode in ("cw", "90", "right"):
        result = rotate_image(path, 90)
    elif mode in ("ccw", "270", "left"):
        result = rotate_image(path, 270)
    elif mode in ("180", "flip"):
        result = rotate_image(path, 180)
    else:
        raise ValueError(f"Unknown rotate mode: {mode}")
    return result, path


def _apply_rotate_result_to_db(media: MediaItem, result: object, path: Path) -> None:
    if not getattr(result, "changed", False):
        return
    if result.width:
        media.width = result.width
    if result.height:
        media.height = result.height
    media.orientation = 1
    media.auto_rotated = True
    media.rotation_degrees = (media.rotation_degrees or 0) + int(
        getattr(result, "degrees_applied", 0) or 0
    )
    try:
        media.file_size = path.stat().st_size
        media.sha256 = sha256_file(path)
    except OSError:
        pass
    ph, dh = compute_perceptual_hashes(path)
    media.phash = ph
    media.dhash = dh
    settings = get_settings()
    generate_still_derivatives(path, media.id, settings)
    media.updated_at = datetime.now(timezone.utc)


@router.post("/batch-rotate", response_model=MediaBatchRotateResponse)
def batch_rotate_media(
    body: MediaBatchRotateRequest,
    db: Session = Depends(get_db),
) -> MediaBatchRotateResponse:
    """Auto-rotate (or manual 90/180) for an entire multi-select batch."""
    if not body.ids:
        raise HTTPException(400, "ids required")
    if len(body.ids) > 200:
        raise HTTPException(400, "Max 200 images per batch rotate")

    mode = (body.mode or "auto").lower().strip()
    aggressive = body.aggressive if body.mode == "auto" else False
    # User batch auto-rotate always aggressive
    if mode == "auto":
        aggressive = True

    rotated: list[str] = []
    unchanged: list[str] = []
    failed: list[dict] = []
    out_items: list[MediaOut] = []

    for mid in body.ids:
        media = (
            db.query(MediaItem)
            .options(joinedload(MediaItem.analysis))
            .filter(MediaItem.id == mid)
            .first()
        )
        if not media:
            failed.append({"id": mid, "error": "not found"})
            continue
        if media.media_type != "image":
            failed.append({"id": mid, "error": "not an image", "filename": media.filename})
            continue
        try:
            result, path = _run_rotate_on_media(media, mode, aggressive=aggressive)
            if result.changed:
                _apply_rotate_result_to_db(media, result, path)
                rotated.append(mid)
            else:
                unchanged.append(mid)
            out_items.append(media_to_out(media))
        except Exception as exc:  # noqa: BLE001
            log.warning("batch_rotate_item_failed", media_id=mid, error=str(exc))
            failed.append(
                {
                    "id": mid,
                    "error": str(exc),
                    "filename": getattr(media, "filename", None),
                }
            )

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("batch_rotate_commit_failed")
        raise HTTPException(500, f"Batch rotate failed: {exc}") from exc

    # Refresh outputs after commit
    refreshed: list[MediaOut] = []
    for mid in [*rotated, *unchanged]:
        m = (
            db.query(MediaItem)
            .options(joinedload(MediaItem.analysis))
            .filter(MediaItem.id == mid)
            .first()
        )
        if m:
            refreshed.append(media_to_out(m))

    return MediaBatchRotateResponse(
        mode=mode,
        rotated=rotated,
        unchanged=unchanged,
        failed=failed,
        count_rotated=len(rotated),
        count_unchanged=len(unchanged),
        count_failed=len(failed),
        items=refreshed,
    )


@router.post("/{media_id}/rotate", response_model=MediaRotateResponse)
def rotate_media(
    media_id: str,
    body: MediaRotateRequest,
    db: Session = Depends(get_db),
) -> MediaRotateResponse:
    """Auto-orient (EXIF + content heuristic) or manual 90°/180° rotate."""
    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")
    if media.media_type != "image":
        raise HTTPException(400, "Only images can be rotated")

    mode = (body.mode or "auto").lower().strip()
    try:
        # Single-item auto from UI also aggressive (user intent = fix rotation)
        result, path = _run_rotate_on_media(
            media, mode, aggressive=(mode == "auto")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.error("rotate_failed", media_id=media_id, error=str(exc))
        raise HTTPException(500, f"Rotate failed: {exc}") from exc

    if result.changed:
        _apply_rotate_result_to_db(media, result, path)
        db.commit()
        db.refresh(media)

    return MediaRotateResponse(
        media=media_to_out(media),
        changed=result.changed,
        method=result.method,
        degrees_applied=result.degrees_applied,
    )


@router.get("/{media_id}/thumb")
def get_thumb(media_id: str, db: Session = Depends(get_db)) -> FileResponse:
    return _file_response(media_id, "thumb", db)


@router.get("/{media_id}/preview")
def get_preview(media_id: str, db: Session = Depends(get_db)) -> FileResponse:
    return _file_response(media_id, "preview", db)


@router.get("/{media_id}/original")
def get_original(media_id: str, db: Session = Depends(get_db)) -> FileResponse:
    media = db.get(MediaItem, media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    path = Path(media.library_path)
    if not path.exists():
        raise HTTPException(404, "Original file missing")
    return FileResponse(
        path,
        filename=media.filename,
        headers={
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )


# Derivatives change on rotate — never let browsers hold a stale thumb/preview.
_DERIVATIVE_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}


def _file_response(media_id: str, kind: str, db: Session) -> FileResponse:
    media = db.get(MediaItem, media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    settings = get_settings()
    if kind == "thumb":
        path = settings.thumbs_dir / f"{media_id}.jpg"
    else:
        path = settings.previews_dir / f"{media_id}.jpg"
    if not path.exists():
        # Fall back to original for images
        orig = Path(media.library_path)
        if orig.exists() and media.media_type == "image":
            return FileResponse(
                orig,
                media_type=media.mime_type or "image/jpeg",
                headers=dict(_DERIVATIVE_CACHE),
            )
        raise HTTPException(404, f"{kind} not found")
    return FileResponse(path, media_type="image/jpeg", headers=dict(_DERIVATIVE_CACHE))
