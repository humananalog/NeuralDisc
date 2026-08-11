"""Disc / ingest endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from neuraldisc.api.schemas import DiscOut, IngestRequest, IngestResponse
from neuraldisc.db.database import get_db
from neuraldisc.db.models import Disc, MediaItem
from neuraldisc.ingest.extractor import Extractor
from neuraldisc.utils.logging import get_logger

router = APIRouter(prefix="/api/discs", tags=["discs"])
log = get_logger(__name__)


@router.get("", response_model=list[DiscOut])
def list_discs(db: Session = Depends(get_db)) -> list[DiscOut]:
    discs = db.query(Disc).order_by(Disc.inserted_at.desc()).all()
    out: list[DiscOut] = []
    for d in discs:
        count = db.query(func.count(MediaItem.id)).filter(MediaItem.disc_id == d.id).scalar() or 0
        out.append(
            DiscOut(
                id=d.id,
                volume_name=d.volume_name,
                volume_uuid=d.volume_uuid,
                filesystem=d.filesystem,
                inserted_at=d.inserted_at,
                extracted_at=d.extracted_at,
                status=d.status,
                notes=d.notes,
                source_path=d.source_path,
                media_count=count,
            )
        )
    return out


@router.get("/{disc_id}", response_model=DiscOut)
def get_disc(disc_id: str, db: Session = Depends(get_db)) -> DiscOut:
    d = db.get(Disc, disc_id)
    if not d:
        raise HTTPException(404, "Disc not found")
    count = db.query(func.count(MediaItem.id)).filter(MediaItem.disc_id == d.id).scalar() or 0
    return DiscOut(
        id=d.id,
        volume_name=d.volume_name,
        volume_uuid=d.volume_uuid,
        filesystem=d.filesystem,
        inserted_at=d.inserted_at,
        extracted_at=d.extracted_at,
        status=d.status,
        notes=d.notes,
        source_path=d.source_path,
        media_count=count,
    )


@router.post("/ingest", response_model=IngestResponse)
def ingest_path(body: IngestRequest) -> IngestResponse:
    path = Path(body.path).expanduser()
    if not path.exists():
        raise HTTPException(400, f"Path does not exist: {path}")
    try:
        result = Extractor().extract(
            path,
            volume_name=body.volume_name,
            process_after=body.process,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest_failed")
        raise HTTPException(500, str(exc)) from exc
    return IngestResponse(
        disc_id=result.disc_id,
        volume_name=result.volume_name,
        files=len(result.files),
        rejected=len(result.rejected),
        reject_samples=[
            f"{r.path.name}: {r.code} — {r.reason}" for r in result.rejected[:20]
        ],
        errors=result.errors,
        provenance_dir=result.provenance_dir,
    )
