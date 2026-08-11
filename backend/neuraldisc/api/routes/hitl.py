"""HITL review queue endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from neuraldisc.api.schemas import HitlItemOut, HitlResolveRequest
from neuraldisc.api.serializers import media_to_out
from neuraldisc.db.database import get_db
from neuraldisc.db.fts import upsert_fts
from neuraldisc.db.models import HitlQueueItem, MediaAnalysis, MediaItem

router = APIRouter(prefix="/api/hitl", tags=["hitl"])


@router.get("/queue", response_model=list[HitlItemOut])
def get_queue(
    limit: int = Query(50, ge=1, le=200),
    queue_type: str | None = None,
    db: Session = Depends(get_db),
) -> list[HitlItemOut]:
    q = (
        db.query(HitlQueueItem)
        .filter(HitlQueueItem.resolved_at.is_(None))
        .order_by(HitlQueueItem.priority.asc(), HitlQueueItem.created_at.asc())
    )
    if queue_type:
        q = q.filter(HitlQueueItem.queue_type == queue_type)
    items = q.limit(limit).all()
    out: list[HitlItemOut] = []
    for item in items:
        media = (
            db.query(MediaItem)
            .options(joinedload(MediaItem.analysis))
            .filter(MediaItem.id == item.media_id)
            .first()
        )
        out.append(
            HitlItemOut(
                id=item.id,
                media_id=item.media_id,
                queue_type=item.queue_type,
                priority=item.priority,
                created_at=item.created_at,
                media=media_to_out(media) if media else None,
            )
        )
    return out


@router.get("/count")
def pending_count(db: Session = Depends(get_db)) -> dict[str, int]:
    count = (
        db.query(HitlQueueItem).filter(HitlQueueItem.resolved_at.is_(None)).count()
    )
    return {"pending": count}


@router.post("/{item_id}/resolve", response_model=HitlItemOut)
def resolve_item(
    item_id: str, body: HitlResolveRequest, db: Session = Depends(get_db)
) -> HitlItemOut:
    item = db.get(HitlQueueItem, item_id)
    if not item or item.resolved_at is not None:
        raise HTTPException(404, "Queue item not found or already resolved")

    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == item.media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")

    if body.resolution not in {"accepted", "rejected", "edited", "deferred"}:
        raise HTTPException(400, "Invalid resolution")

    if body.resolution == "deferred":
        item.priority = max(item.priority, 200)
        db.commit()
        return HitlItemOut(
            id=item.id,
            media_id=item.media_id,
            queue_type=item.queue_type,
            priority=item.priority,
            created_at=item.created_at,
            media=media_to_out(media),
        )

    item.resolved_at = datetime.now(timezone.utc)
    item.resolution = body.resolution
    media.hitl_status = body.resolution
    media.updated_at = datetime.now(timezone.utc)

    if body.rating is not None:
        media.rating = max(0, min(5, body.rating))
    if body.flag is not None:
        media.flag = body.flag

    if body.caption_short is not None or body.description is not None or body.suggested_tags is not None:
        analysis = media.analysis
        if analysis is None:
            analysis = MediaAnalysis(media_id=media.id)
            db.add(analysis)
        if body.caption_short is not None:
            analysis.caption_short = body.caption_short
        if body.description is not None:
            analysis.description = body.description
        if body.suggested_tags is not None:
            analysis.suggested_tags = json.dumps(body.suggested_tags)
        analysis.human_edited = True
        if body.resolution == "accepted":
            media.hitl_status = "edited"
            item.resolution = "edited"
        db.flush()
        upsert_fts(db, media, analysis)

    db.commit()
    db.refresh(media)
    return HitlItemOut(
        id=item.id,
        media_id=item.media_id,
        queue_type=item.queue_type,
        priority=item.priority,
        created_at=item.created_at,
        media=media_to_out(media),
    )


@router.post("/batch/accept")
def batch_accept(
    media_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    updated = 0
    for mid in media_ids:
        media = db.get(MediaItem, mid)
        if not media:
            continue
        media.hitl_status = "accepted"
        media.updated_at = now
        for item in (
            db.query(HitlQueueItem)
            .filter(HitlQueueItem.media_id == mid, HitlQueueItem.resolved_at.is_(None))
            .all()
        ):
            item.resolved_at = now
            item.resolution = "accepted"
        updated += 1
    db.commit()
    return {"updated": updated}
