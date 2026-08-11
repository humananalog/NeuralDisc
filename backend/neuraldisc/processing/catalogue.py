"""Catalogue lifecycle: trash (soft delete) and permanent purge.

Best practices (Apple Photos / Immich / Lightroom):
- Soft-delete first → lifecycle=trash + deleted_at
- Hidden from default library views
- Restorable until permanent purge
- Permanent delete removes originals, derivatives, FTS, album links, dupe members, HITL
- Actions are logged
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from neuraldisc.config import Settings, get_settings
from neuraldisc.db.models import (
    AlbumItem,
    DuplicateGroup,
    DuplicateMember,
    EmbeddingMeta,
    HitlQueueItem,
    MediaAnalysis,
    MediaItem,
)
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


def soft_delete_media(session: Session, media: MediaItem) -> MediaItem:
    """Move item to trash. Idempotent if already trashed."""
    now = datetime.now(timezone.utc)
    if (media.lifecycle or "") == "trash" and media.deleted_at is not None:
        return media
    media.lifecycle = "trash"
    media.deleted_at = now
    media.updated_at = now
    # Close open HITL items
    for item in (
        session.query(HitlQueueItem)
        .filter(HitlQueueItem.media_id == media.id, HitlQueueItem.resolved_at.is_(None))
        .all()
    ):
        item.resolved_at = now
        item.resolution = "trashed"
    session.flush()
    log.info("media_trashed", media_id=media.id, filename=media.filename)
    return media


def restore_media(session: Session, media: MediaItem) -> MediaItem:
    """Restore from trash back into the library."""
    if (media.lifecycle or "") != "trash":
        return media
    media.lifecycle = "library"
    media.deleted_at = None
    media.updated_at = datetime.now(timezone.utc)
    session.flush()
    log.info("media_restored", media_id=media.id, filename=media.filename)
    return media


def permanent_delete_media(
    session: Session,
    media: MediaItem,
    settings: Settings | None = None,
    *,
    delete_files: bool = True,
) -> str:
    """Irreversibly remove DB rows and (by default) files on disk.

    Clears every FK that points at this media before DELETE so SQLite
    foreign_keys=ON does not raise IntegrityError (e.g. duplicate_groups.best_media_id).

    Returns the deleted media id.
    """
    settings = settings or get_settings()
    mid = media.id
    filename = media.filename
    library_path = media.library_path

    # FTS
    try:
        session.execute(text("DELETE FROM media_fts WHERE media_id = :id"), {"id": mid})
    except Exception as exc:  # noqa: BLE001
        log.debug("fts_delete_failed", media_id=mid, error=str(exc))

    # Null FK pointers that reference this media (must come before DELETE)
    session.query(DuplicateGroup).filter(DuplicateGroup.best_media_id == mid).update(
        {DuplicateGroup.best_media_id: None},
        synchronize_session=False,
    )

    # Related child rows
    session.query(AlbumItem).filter(AlbumItem.media_id == mid).delete(synchronize_session=False)
    session.query(DuplicateMember).filter(DuplicateMember.media_id == mid).delete(
        synchronize_session=False
    )
    session.query(HitlQueueItem).filter(HitlQueueItem.media_id == mid).delete(
        synchronize_session=False
    )
    session.query(MediaAnalysis).filter(MediaAnalysis.media_id == mid).delete(
        synchronize_session=False
    )
    session.query(EmbeddingMeta).filter(EmbeddingMeta.media_id == mid).delete(
        synchronize_session=False
    )

    # Drop empty duplicate groups left with 0 members
    try:
        session.execute(
            text(
                """
                DELETE FROM duplicate_groups
                WHERE id NOT IN (
                    SELECT DISTINCT group_id FROM duplicate_members
                    WHERE group_id IS NOT NULL
                )
                """
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("empty_group_cleanup_failed", error=str(exc))

    if delete_files:
        _delete_files(mid, library_path, settings)

    session.delete(media)
    session.flush()
    log.info("media_permanently_deleted", media_id=mid, filename=filename)
    return mid


def _delete_files(media_id: str, library_path: str | None, settings: Settings) -> None:
    if library_path:
        p = Path(library_path)
        try:
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except OSError as exc:
            log.warning("original_delete_failed", path=str(p), error=str(exc))

    for d in (settings.thumbs_dir, settings.previews_dir):
        for f in d.glob(f"{media_id}.*"):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

    kf = settings.keyframes_dir / media_id
    if kf.exists():
        shutil.rmtree(kf, ignore_errors=True)
