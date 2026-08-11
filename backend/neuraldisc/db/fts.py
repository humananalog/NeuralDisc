"""FTS5 index maintenance helpers."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from neuraldisc.db.models import MediaAnalysis, MediaItem


def upsert_fts(session: Session, media: MediaItem, analysis: MediaAnalysis | None = None) -> None:
    analysis = analysis or media.analysis
    objects = ""
    tags = ""
    caption = description = scene = people = None
    if analysis:
        caption = analysis.caption_short
        description = analysis.description
        scene = analysis.scene_type
        people = analysis.people_desc
        objects = _json_list_to_text(analysis.objects)
        tags = _json_list_to_text(analysis.suggested_tags)

    session.execute(text("DELETE FROM media_fts WHERE media_id = :id"), {"id": media.id})
    session.execute(
        text(
            """
            INSERT INTO media_fts (
                media_id, filename, caption_short, description, scene_type,
                people_desc, objects, suggested_tags, camera_make, camera_model
            ) VALUES (
                :media_id, :filename, :caption_short, :description, :scene_type,
                :people_desc, :objects, :suggested_tags, :camera_make, :camera_model
            )
            """
        ),
        {
            "media_id": media.id,
            "filename": media.filename or "",
            "caption_short": caption or "",
            "description": description or "",
            "scene_type": scene or "",
            "people_desc": people or "",
            "objects": objects,
            "suggested_tags": tags,
            "camera_make": media.camera_make or "",
            "camera_model": media.camera_model or "",
        },
    )


def search_fts(session: Session, query: str, limit: int = 50) -> list[str]:
    """Return media_ids matching FTS query."""
    if not query.strip():
        return []
    # Escape FTS5 special chars roughly
    safe = query.replace('"', '""')
    rows = session.execute(
        text(
            """
            SELECT media_id FROM media_fts
            WHERE media_fts MATCH :q
            ORDER BY rank
            LIMIT :limit
            """
        ),
        {"q": safe, "limit": limit},
    ).fetchall()
    return [r[0] for r in rows]


def _json_list_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data: Any = json.loads(raw)
        if isinstance(data, list):
            return " ".join(str(x) for x in data)
        return str(data)
    except json.JSONDecodeError:
        return raw
