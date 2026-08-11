"""Albums / collections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from neuraldisc.api.schemas import AlbumCreate, AlbumOut
from neuraldisc.db.database import get_db
from neuraldisc.db.models import Album, AlbumItem

router = APIRouter(prefix="/api/albums", tags=["albums"])


@router.get("", response_model=list[AlbumOut])
def list_albums(db: Session = Depends(get_db)) -> list[AlbumOut]:
    albums = db.query(Album).order_by(Album.created_at.desc()).all()
    out: list[AlbumOut] = []
    for a in albums:
        count = db.query(func.count(AlbumItem.media_id)).filter(AlbumItem.album_id == a.id).scalar() or 0
        cover = (
            db.query(AlbumItem.media_id)
            .filter(AlbumItem.album_id == a.id)
            .order_by(AlbumItem.position.asc().nullslast())
            .first()
        )
        out.append(
            AlbumOut(
                id=a.id,
                name=a.name,
                description=a.description,
                is_ai_proposed=a.is_ai_proposed,
                created_at=a.created_at,
                item_count=count,
                cover_media_id=cover[0] if cover else None,
            )
        )
    return out


@router.post("", response_model=AlbumOut)
def create_album(body: AlbumCreate, db: Session = Depends(get_db)) -> AlbumOut:
    album = Album(name=body.name, description=body.description)
    db.add(album)
    db.flush()
    for i, mid in enumerate(body.media_ids):
        db.add(AlbumItem(album_id=album.id, media_id=mid, position=i))
    db.commit()
    db.refresh(album)
    return AlbumOut(
        id=album.id,
        name=album.name,
        description=album.description,
        is_ai_proposed=album.is_ai_proposed,
        created_at=album.created_at,
        item_count=len(body.media_ids),
        cover_media_id=body.media_ids[0] if body.media_ids else None,
    )


@router.get("/{album_id}", response_model=AlbumOut)
def get_album(album_id: str, db: Session = Depends(get_db)) -> AlbumOut:
    a = db.get(Album, album_id)
    if not a:
        raise HTTPException(404, "Album not found")
    count = db.query(func.count(AlbumItem.media_id)).filter(AlbumItem.album_id == a.id).scalar() or 0
    cover = (
        db.query(AlbumItem.media_id)
        .filter(AlbumItem.album_id == a.id)
        .order_by(AlbumItem.position.asc().nullslast())
        .first()
    )
    return AlbumOut(
        id=a.id,
        name=a.name,
        description=a.description,
        is_ai_proposed=a.is_ai_proposed,
        created_at=a.created_at,
        item_count=count,
        cover_media_id=cover[0] if cover else None,
    )
