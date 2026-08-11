"""Duplicate group endpoints — list + keep-best (single & batch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fastapi import Query

from neuraldisc.ai.duplicates import (
    duplicate_summary,
    keep_best_batch,
    keep_best_for_group,
    list_duplicate_groups,
    prune_resolved_duplicate_groups,
)
from neuraldisc.api.schemas import DuplicateGroupOut
from neuraldisc.db.database import get_db
from neuraldisc.db.models import DuplicateGroup

router = APIRouter(prefix="/api/duplicates", tags=["duplicates"])


class KeepBestBatchRequest(BaseModel):
    """Resolve keep-best across many groups or a multi-select batch.

    Provide one of:
    - ``all_groups=true`` — every duplicate group
    - ``group_ids`` — specific groups
    - ``media_ids`` — grid multi-select (clusters by group + ad-hoc)
    """

    group_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    all_groups: bool = False
    trash_losers: bool = True  # soft-delete non-winners (catalogue default)


@router.get("/summary")
def get_duplicate_summary(db: Session = Depends(get_db)) -> dict:
    """Top counts for the Duplicates page header and nav badge."""
    out = duplicate_summary(db)
    db.commit()  # persist prune from summary
    return out


@router.get("", response_model=list[DuplicateGroupOut])
def list_groups(
    include_resolved: bool = Query(
        False,
        description="If true, include groups with <2 library members (ghosts)",
    ),
    db: Session = Depends(get_db),
) -> list[dict]:
    out = list_duplicate_groups(db, include_resolved=include_resolved, prune=True)
    db.commit()  # persist prune so next load stays clean
    return out


@router.post("/cleanup")
def cleanup_resolved(db: Session = Depends(get_db)) -> dict:
    """Remove trashed members from groups and dissolve resolved groups."""
    result = prune_resolved_duplicate_groups(db)
    db.commit()
    return result


@router.post("/keep-best-batch")
def keep_best_batch_endpoint(
    body: KeepBestBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Keep best for an entire batch selection or all/many groups at once."""
    if not body.all_groups and not body.group_ids and not body.media_ids:
        raise HTTPException(
            400,
            "Provide media_ids, group_ids, or all_groups=true",
        )
    if body.media_ids and len(body.media_ids) > 2000:
        raise HTTPException(400, "Max 2000 media_ids per batch")
    if body.group_ids and len(body.group_ids) > 500:
        raise HTTPException(400, "Max 500 group_ids per batch")

    result = keep_best_batch(
        db,
        group_ids=body.group_ids or None,
        media_ids=body.media_ids or None,
        all_groups=body.all_groups,
        trash_losers=body.trash_losers,
    )
    db.commit()
    return result.as_dict()


@router.post("/{group_id}/keep-best")
def keep_best(group_id: str, db: Session = Depends(get_db)) -> dict:
    group = db.get(DuplicateGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    result = keep_best_for_group(db, group_id, trash_losers=True)
    db.commit()
    kept = result.kept[0] if result.kept else group.best_media_id
    return {
        "kept": kept,
        "rejected": len(result.trashed) + len(result.rejected),
        "trashed": result.trashed,
        **result.as_dict(),
    }
