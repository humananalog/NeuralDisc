"""Repair wrong ``taken_at`` values that were set to import/copy time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from neuraldisc.db.models import MediaItem
from neuraldisc.processing.metadata import (
    ExifToolError,
    ExifToolNotFoundError,
    extract_metadata,
    _looks_like_import_clock,
)
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class DatesRepairResult:
    scanned: int = 0
    updated: int = 0
    cleared: int = 0
    skipped: int = 0
    missing_file: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "updated": self.updated,
            "cleared": self.cleared,
            "skipped": self.skipped,
            "missing_file": self.missing_file,
            "errors": self.errors,
        }


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def taken_at_looks_suspicious(media: MediaItem) -> bool:
    """True when stored taken_at is missing or likely import/copy clock."""
    taken = _aware(media.taken_at)
    if taken is None:
        return True
    if _looks_like_import_clock(taken):
        return True
    created = _aware(media.created_at)
    if created is not None:
        if abs((taken - created).total_seconds()) < 2 * 86400:
            return True
    return False


def repair_taken_at(
    session: Session,
    *,
    dry_run: bool = False,
    only_suspicious: bool = True,
    limit: int | None = None,
) -> DatesRepairResult:
    """Re-resolve capture dates from EXIF / original path / filesystem.

    Prefer capture EXIF tags and dates embedded in folder names (e.g.
    ``Gleniff Forest Park 28-02-2005``). Never trust FileModifyDate alone.
    """
    result = DatesRepairResult()
    q = session.query(MediaItem).order_by(MediaItem.created_at.asc())
    if limit is not None:
        q = q.limit(limit)
    items = q.all()

    for media in items:
        result.scanned += 1
        if only_suspicious and not taken_at_looks_suspicious(media):
            result.skipped += 1
            continue

        path = Path(media.library_path)
        if not path.is_file():
            result.missing_file += 1
            continue

        try:
            meta = extract_metadata(
                path,
                media.media_type,
                original_relpath=media.original_path,
            )
        except ExifToolNotFoundError:
            raise
        except (ExifToolError, OSError) as exc:
            result.errors += 1
            log.warning(
                "dates_repair_exif_failed",
                media_id=media.id,
                filename=media.filename,
                error=str(exc),
            )
            continue

        new_taken = _aware(meta.taken_at)
        old_taken = _aware(media.taken_at)

        # Do not replace a historical date with a near-now filesystem fallback
        if (
            new_taken is not None
            and meta.taken_at_source in ("mtime", "birthtime")
            and _looks_like_import_clock(new_taken)
        ):
            new_taken = None

        if new_taken == old_taken:
            result.skipped += 1
            continue

        if dry_run:
            if new_taken is None and old_taken is not None:
                result.cleared += 1
            else:
                result.updated += 1
            log.info(
                "dates_repair_would_change",
                media_id=media.id,
                filename=media.filename,
                old=old_taken.isoformat() if old_taken else None,
                new=new_taken.isoformat() if new_taken else None,
                source=meta.taken_at_source,
                original_path=media.original_path,
            )
            continue

        media.taken_at = new_taken
        media.updated_at = datetime.now(timezone.utc)
        if new_taken is None and old_taken is not None:
            result.cleared += 1
        else:
            result.updated += 1
        log.info(
            "dates_repair_updated",
            media_id=media.id,
            filename=media.filename,
            old=old_taken.isoformat() if old_taken else None,
            new=new_taken.isoformat() if new_taken else None,
            source=meta.taken_at_source,
        )

    if not dry_run and (result.updated or result.cleared):
        session.flush()

    return result
