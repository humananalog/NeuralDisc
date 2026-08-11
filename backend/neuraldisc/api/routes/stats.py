"""Library statistics and sidebar nav counts."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from neuraldisc.api.schemas import NavCountsOut, StatsOut
from neuraldisc.db.database import get_db
from neuraldisc.db.models import Album, Disc, Job, MediaAnalysis, MediaItem

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _library_filter():
    return or_(MediaItem.lifecycle == "library", MediaItem.lifecycle.is_(None))


@router.get("", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    lib = _library_filter()
    total = db.query(func.count(MediaItem.id)).filter(lib).scalar() or 0
    images = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.media_type == "image")
        .scalar()
        or 0
    )
    videos = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.media_type == "video")
        .scalar()
        or 0
    )
    discs = db.query(func.count(Disc.id)).scalar() or 0
    pending = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.hitl_status == "pending")
        .scalar()
        or 0
    )
    accepted = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.hitl_status == "accepted")
        .scalar()
        or 0
    )
    rejected = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.hitl_status == "rejected")
        .scalar()
        or 0
    )
    duplicates = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.is_duplicate.is_(True))
        .scalar()
        or 0
    )
    blurry = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.is_blurry.is_(True))
        .scalar()
        or 0
    )
    storage = (
        db.query(func.coalesce(func.sum(MediaItem.file_size), 0)).filter(lib).scalar() or 0
    )
    has_gps = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.gps_lat.isnot(None))
        .scalar()
        or 0
    )
    albums = db.query(func.count(Album.id)).scalar() or 0
    people = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(lib, MediaAnalysis.people_count.isnot(None), MediaAnalysis.people_count > 0)
        .scalar()
        or 0
    )
    timeline = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.taken_at.isnot(None))
        .scalar()
        or 0
    )
    trash = (
        db.query(func.count(MediaItem.id)).filter(MediaItem.lifecycle == "trash").scalar() or 0
    )
    jobs_active = (
        db.query(func.count(Job.id))
        .filter(Job.status.in_(("queued", "running")))
        .scalar()
        or 0
    )

    # Active duplicate groups (alive members ≥ 2) — light count via is_duplicate flag groups
    # Prefer summary-style: media marked duplicate is cheaper than walking groups here
    from neuraldisc.ai.duplicates import duplicate_summary

    dup_sum = duplicate_summary(db)

    return StatsOut(
        total_media=total,
        total_images=images,
        total_videos=videos,
        total_discs=discs,
        pending_review=pending,
        accepted=accepted,
        rejected=rejected,
        duplicates=duplicates,
        blurry=blurry,
        storage_bytes=int(storage),
        has_gps=has_gps,
        albums=albums,
        people=people,
        timeline=timeline,
        trash=trash,
        jobs_active=jobs_active,
        duplicate_groups=dup_sum.get("active_groups", 0),
    )


@router.get("/nav", response_model=NavCountsOut)
def get_nav_counts(db: Session = Depends(get_db)) -> NavCountsOut:
    """Single payload for left-nav counters on every section."""
    lib = _library_filter()

    library = db.query(func.count(MediaItem.id)).filter(lib).scalar() or 0
    images = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.media_type == "image")
        .scalar()
        or 0
    )
    videos = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.media_type == "video")
        .scalar()
        or 0
    )
    timeline = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.taken_at.isnot(None))
        .scalar()
        or 0
    )
    has_gps = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.gps_lat.isnot(None))
        .scalar()
        or 0
    )
    people = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(
            lib,
            MediaAnalysis.people_count.isnot(None),
            MediaAnalysis.people_count > 0,
        )
        .scalar()
        or 0
    )
    albums = db.query(func.count(Album.id)).scalar() or 0
    review = (
        db.query(func.count(MediaItem.id))
        .filter(lib, MediaItem.hitl_status == "pending")
        .scalar()
        or 0
    )
    jobs = (
        db.query(func.count(Job.id))
        .filter(Job.status.in_(("queued", "running")))
        .scalar()
        or 0
    )
    discs = db.query(func.count(Disc.id)).scalar() or 0
    trash = (
        db.query(func.count(MediaItem.id)).filter(MediaItem.lifecycle == "trash").scalar() or 0
    )

    from neuraldisc.ai.duplicates import duplicate_summary

    dup_sum = duplicate_summary(db)
    duplicates = int(dup_sum.get("active_groups") or 0)

    # Settings: count configured secrets (HF etc.)
    try:
        from neuraldisc.secrets_store import list_secret_status

        settings_n = sum(
            1 for v in list_secret_status().values() if isinstance(v, dict) and v.get("configured")
        )
    except Exception:  # noqa: BLE001
        settings_n = 0

    return NavCountsOut(
        library=library,
        timeline=timeline,
        grid=library,
        map=has_gps,
        people=people,
        albums=albums,
        duplicates=duplicates,
        review=review,
        jobs=jobs,
        stats=discs,  # disc provenance count on Stats nav
        settings=settings_n,
        images=images,
        videos=videos,
        discs=discs,
        trash=trash,
    )
