"""Albums, smart collections, and auto-organisation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from neuraldisc.api.schemas import (
    AlbumCreate,
    AlbumOut,
    AutoOrganiseRequest,
    AutoOrganiseResponse,
    MediaListResponse,
    SmartCollectionCreate,
)
from neuraldisc.api.serializers import media_to_out
from neuraldisc.config import get_settings
from neuraldisc.db.database import get_db
from neuraldisc.db.models import Album, AlbumItem, MediaItem
from neuraldisc.processing.organisation import (
    album_member_ids,
    auto_organise,
    resolve_smart_media_ids,
)
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/albums", tags=["albums"])


def _rules_dict(album: Album) -> dict | None:
    if not album.rules_json:
        return None
    try:
        data = json.loads(album.rules_json)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _item_count(db: Session, album: Album) -> int:
    if (album.kind or "album") == "smart":
        rules = _rules_dict(album) or {}
        return len(resolve_smart_media_ids(db, rules, limit=5000))
    return (
        db.query(func.count(AlbumItem.media_id)).filter(AlbumItem.album_id == album.id).scalar()
        or 0
    )


def _cover(db: Session, album: Album) -> str | None:
    if album.cover_media_id:
        return album.cover_media_id
    ids = album_member_ids(db, album, limit=1)
    return ids[0] if ids else None


def album_to_out(db: Session, a: Album) -> AlbumOut:
    return AlbumOut(
        id=a.id,
        name=a.name,
        description=a.description,
        is_ai_proposed=bool(a.is_ai_proposed),
        kind=a.kind or "album",
        source=a.source,
        auto_key=a.auto_key,
        rules=_rules_dict(a),
        created_at=a.created_at,
        updated_at=getattr(a, "updated_at", None),
        item_count=_item_count(db, a),
        cover_media_id=_cover(db, a),
    )


def _auto_name_from_rules(rules: dict) -> str:
    """Human title when user doesn't supply a smart-collection name."""
    if rules.get("year") is not None:
        return f"Year {rules['year']}"
    if rules.get("year_month"):
        return f"Month {rules['year_month']}"
    if rules.get("camera_model") or rules.get("camera_make"):
        return " ".join(
            p
            for p in (rules.get("camera_make"), rules.get("camera_model"))
            if p
        ) or "Camera"
    if rules.get("scene_type"):
        return str(rules["scene_type"]).replace("_", " ").title()
    if rules.get("tag"):
        return f"#{rules['tag']}"
    if rules.get("media_type") == "video":
        return "Videos"
    if rules.get("media_type") == "image":
        return "Photos"
    if rules.get("has_gps") is True:
        return "On the map"
    if rules.get("is_blurry") is True:
        return "Blurry shots"
    if rules.get("people_min"):
        return "With people"
    if rules.get("hitl_status") == "pending":
        return "Needs review"
    if rules.get("q"):
        return f"Search: {rules['q']}"
    return "Smart collection"


@router.get("", response_model=list[AlbumOut])
def list_albums(
    kind: str | None = Query(None, description="album | smart"),
    source: str | None = None,
    db: Session = Depends(get_db),
) -> list[AlbumOut]:
    q = db.query(Album)
    if kind:
        q = q.filter(Album.kind == kind)
    if source:
        q = q.filter(Album.source == source)
    albums = q.order_by(Album.updated_at.desc().nullslast(), Album.created_at.desc()).all()
    return [album_to_out(db, a) for a in albums]


@router.post("", response_model=AlbumOut)
def create_album(body: AlbumCreate, db: Session = Depends(get_db)) -> AlbumOut:
    kind = (body.kind or "album").lower()
    if kind not in ("album", "smart"):
        raise HTTPException(400, "kind must be album or smart")
    album = Album(
        name=body.name,
        description=body.description,
        kind=kind,
        source="user",
        is_ai_proposed=False,
        rules_json=json.dumps(body.rules) if body.rules else None,
    )
    db.add(album)
    db.flush()
    if kind == "album":
        for i, mid in enumerate(body.media_ids):
            db.add(AlbumItem(album_id=album.id, media_id=mid, position=i))
        if body.media_ids:
            album.cover_media_id = body.media_ids[0]
    db.commit()
    db.refresh(album)
    return album_to_out(db, album)


@router.post("/smart", response_model=AlbumOut)
def create_smart_collection(
    body: SmartCollectionCreate, db: Session = Depends(get_db)
) -> AlbumOut:
    """Create a smart collection; auto-names from rules when name omitted."""
    if not body.rules:
        raise HTTPException(400, "rules required")
    name = (body.name or "").strip() or _auto_name_from_rules(body.rules)
    desc = body.description or "User smart collection (dynamic rules)."
    # Stable-ish key from rules
    key_bits = sorted(f"{k}={v}" for k, v in body.rules.items())
    auto_key = "smart:user:" + str(abs(hash("|".join(key_bits))))[:12]

    existing = db.query(Album).filter(Album.auto_key == auto_key).first()
    ids = resolve_smart_media_ids(db, body.rules)
    now = datetime.now(timezone.utc)
    if existing:
        existing.name = name
        existing.description = desc
        existing.rules_json = json.dumps(body.rules)
        existing.kind = "smart"
        existing.updated_at = now
        existing.cover_media_id = ids[0] if ids else existing.cover_media_id
        db.commit()
        db.refresh(existing)
        return album_to_out(db, existing)

    album = Album(
        name=name,
        description=desc,
        kind="smart",
        source="smart_user",
        is_ai_proposed=False,
        auto_key=auto_key,
        rules_json=json.dumps(body.rules),
        cover_media_id=ids[0] if ids else None,
        created_at=now,
        updated_at=now,
    )
    db.add(album)
    db.commit()
    db.refresh(album)
    return album_to_out(db, album)


@router.post("/auto-organise", response_model=AutoOrganiseResponse)
def run_auto_organise(
    body: AutoOrganiseRequest | None = None,
    db: Session = Depends(get_db),
) -> AutoOrganiseResponse:
    """Generate auto-named albums + smart collections from EXIF + inference."""
    body = body or AutoOrganiseRequest()
    try:
        result = auto_organise(
            db,
            include_years=body.include_years,
            include_months=body.include_months,
            include_cameras=body.include_cameras,
            include_scenes=body.include_scenes,
            include_tags=body.include_tags,
            include_discs=body.include_discs,
            include_events=body.include_events,
            include_people=body.include_people,
            include_smart=body.include_smart,
            min_members=max(2, body.min_members),
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("auto_organise_failed")
        raise HTTPException(500, f"Auto-organise failed: {exc}") from exc

    albums = (
        db.query(Album)
        .order_by(Album.updated_at.desc().nullslast())
        .limit(100)
        .all()
    )
    return AutoOrganiseResponse(
        **result.as_dict(),
        albums=[album_to_out(db, a) for a in albums],
    )


@router.get("/{album_id}", response_model=AlbumOut)
def get_album(album_id: str, db: Session = Depends(get_db)) -> AlbumOut:
    a = db.get(Album, album_id)
    if not a:
        raise HTTPException(404, "Album not found")
    return album_to_out(db, a)


@router.get("/{album_id}/media", response_model=MediaListResponse)
def album_media(
    album_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MediaListResponse:
    a = db.get(Album, album_id)
    if not a:
        raise HTTPException(404, "Album not found")
    ids = album_member_ids(db, a, limit=5000)
    total = len(ids)
    page_ids = ids[offset : offset + limit]
    if not page_ids:
        return MediaListResponse(items=[], total=total, offset=offset, limit=limit)

    # Preserve order
    rows = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id.in_(page_ids))
        .all()
    )
    by_id = {m.id: m for m in rows}
    settings = get_settings()
    items = [media_to_out(by_id[i], settings) for i in page_ids if i in by_id]
    return MediaListResponse(items=items, total=total, offset=offset, limit=limit)


@router.delete("/{album_id}")
def delete_album(album_id: str, db: Session = Depends(get_db)) -> dict:
    a = db.get(Album, album_id)
    if not a:
        raise HTTPException(404, "Album not found")
    db.query(AlbumItem).filter(AlbumItem.album_id == album_id).delete(synchronize_session=False)
    db.delete(a)
    db.commit()
    return {"deleted": album_id}
