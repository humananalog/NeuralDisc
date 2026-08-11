"""Post-ingest processing pipeline + promote-to-library."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from neuraldisc.ai.duplicates import find_duplicates_for_media
from neuraldisc.ai.embeddings import generate_embedding
from neuraldisc.ai.vlm import analyse_media, release_vlm, vlm_session
from neuraldisc.config import Settings, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.fts import upsert_fts
from neuraldisc.db.models import HitlQueueItem, Job, MediaAnalysis, MediaItem
from neuraldisc.processing.blur import detect_blur
from neuraldisc.processing.derivatives import generate_still_derivatives, generate_video_derivatives
from neuraldisc.processing.hashes import compute_perceptual_hashes
from neuraldisc.processing.metadata import (
    ExifToolError,
    ExifToolNotFoundError,
    extract_metadata,
)
from neuraldisc.processing.orientation import auto_orient_image
from neuraldisc.processing.quality import evaluate_media_item
from neuraldisc.utils.hashing import sha256_file
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

ProcessResult = Literal["promoted", "rejected", "error", "ok"]


def enqueue_post_ingest(disc_id: str) -> str:
    """Create a job row and run processing (sync for reliability; async worker optional)."""
    with session_scope() as session:
        job = Job(
            job_type="post_ingest",
            status="queued",
            message=f"Post-ingest for disc {disc_id}",
            payload=json.dumps({"disc_id": disc_id}),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    from neuraldisc.jobs.control import clear_cancel, mark_cancelled, register_job

    register_job(job_id)

    try:
        process_disc(disc_id, job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("post_ingest_failed", disc_id=disc_id)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status != "cancelled":
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(timezone.utc)
    finally:
        # Free VLM / Metal for peer apps (mlx_lm :8088, etc.)
        try:
            rel = release_vlm(force=True)
            log.info("post_ingest_mlx_released", disc_id=disc_id, **rel)
        except Exception as rel_exc:  # noqa: BLE001
            log.warning("post_ingest_release_failed", error=str(rel_exc))
        # If still running after process_disc returned early due to cancel, ensure status
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status == "running":
                from neuraldisc.jobs.control import is_cancel_requested

                if is_cancel_requested(job_id):
                    mark_cancelled(job_id, "Cancelled during post-ingest")
        clear_cancel(job_id)
    return job_id


def process_disc(disc_id: str, job_id: str | None = None) -> None:
    from neuraldisc.jobs.control import is_cancel_requested, mark_cancelled

    settings = get_settings()
    with session_scope() as session:
        items = (
            session.query(MediaItem)
            .filter(MediaItem.disc_id == disc_id)
            .order_by(MediaItem.created_at)
            .all()
        )
        media_ids = [m.id for m in items]
        provenance = None
        originals_root = None
        if items:
            # Infer provenance folder from first item path parent name
            p = Path(items[0].library_path)
            provenance = p.parent.name
            originals_root = settings.originals_dir / provenance
        if job_id:
            job = session.get(Job, job_id)
            if job:
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.total = len(media_ids)
                job.message = f"Processing {len(media_ids)} items"

    cancelled = False
    # Hold VLM for the whole disc batch; release on exit for peer MLX apps
    with vlm_session(release_on_exit=True):
        for i, mid in enumerate(media_ids):
            if job_id and is_cancel_requested(job_id):
                cancelled = True
                mark_cancelled(
                    job_id,
                    f"Cancelled after {i}/{len(media_ids)} items",
                )
                log.info("post_ingest_cancelled", disc_id=disc_id, completed=i)
                break
            try:
                process_media_item(
                    mid,
                    settings,
                    promote=settings.import_stage_until_classified,
                    provenance=provenance,
                    originals_root=originals_root,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("process_item_failed", media_id=mid, error=str(exc))
            if job_id:
                with session_scope() as session:
                    job = session.get(Job, job_id)
                    if job and job.status != "cancelled":
                        job.completed = i + 1
                        job.progress = (i + 1) / max(len(media_ids), 1)
                        job.message = f"Processed {i + 1}/{len(media_ids)}"

    if job_id and not cancelled:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status != "cancelled":
                job.status = "completed"
                job.progress = 1.0
                job.finished_at = datetime.now(timezone.utc)
                job.message = f"Completed {len(media_ids)} items · MLX released"


def process_media_item(
    media_id: str,
    settings: Settings | None = None,
    *,
    promote: bool = True,
    provenance: str | None = None,
    originals_root: Path | None = None,
) -> ProcessResult:
    """Process one media file while still in staging; promote only if classified OK."""
    settings = settings or get_settings()
    with session_scope() as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            return "error"
        path = Path(media.library_path)
        if not path.exists():
            log.warning("media_missing", media_id=media_id, path=str(path))
            return "error"

        # Metadata — exiftool is mandatory
        try:
            meta = extract_metadata(path, media.media_type)
        except ExifToolNotFoundError:
            log.error("exiftool_required_missing", media_id=media.id)
            raise
        except ExifToolError as exc:
            log.warning("exiftool_failed", media_id=media.id, error=str(exc))
            # Soft-fail single file: keep processing with empty EXIF rather than
            # aborting whole import; dimensions may still come from quality later
            meta = None

        if meta is not None:
            media.width = meta.width
            media.height = meta.height
            media.mime_type = meta.mime_type
            media.taken_at = meta.taken_at
            media.camera_make = meta.camera_make
            media.camera_model = meta.camera_model
            media.gps_lat = meta.gps_lat
            media.gps_lon = meta.gps_lon
            media.orientation = meta.orientation
            media.duration_ms = meta.duration_ms
        media.updated_at = datetime.now(timezone.utc)
        session.flush()

        # SOTA auto-rotate: bake EXIF Orientation (+ content upright fallback)
        # before quality / derivatives so all downstream steps see upright pixels.
        if (
            media.media_type == "image"
            and settings.auto_rotate_enabled
            and path.exists()
        ):
            try:
                orient = auto_orient_image(
                    path,
                    content_fallback=settings.auto_rotate_content_fallback,
                )
                if orient.changed:
                    media.auto_rotated = True
                    media.rotation_degrees = (media.rotation_degrees or 0) + orient.degrees_applied
                    media.orientation = 1
                    if orient.width:
                        media.width = orient.width
                    if orient.height:
                        media.height = orient.height
                    try:
                        media.file_size = path.stat().st_size
                        media.sha256 = sha256_file(path)
                    except OSError:
                        pass
                    log.info(
                        "auto_rotated",
                        media_id=media.id,
                        method=orient.method,
                        degrees=orient.degrees_applied,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_orient_step_failed", media_id=media.id, error=str(exc))

        # Second-pass quality gate
        if settings.quality_enabled:
            verdict = evaluate_media_item(
                path,
                media_type=media.media_type,
                width=media.width,
                height=media.height,
                file_size=media.file_size,
                settings=settings,
            )
            if verdict.rejected:
                _purge_rejected_media(session, media, settings, verdict.code, verdict.reason)
                log.info(
                    "quality_purge",
                    media_id=media.id,
                    filename=media.filename,
                    code=verdict.code,
                    reason=verdict.reason,
                )
                return "rejected"

        # Derivatives + hashes (from staging path — already upright)
        if media.media_type == "image":
            generate_still_derivatives(path, media.id, settings)
            ph, dh = compute_perceptual_hashes(path)
            media.phash = ph
            media.dhash = dh
            blur_source = path
        else:
            generate_video_derivatives(path, media.id, settings)
            thumb = settings.thumbs_dir / f"{media.id}.jpg"
            if thumb.exists():
                ph, dh = compute_perceptual_hashes(thumb)
                media.phash = ph
                media.dhash = dh
            blur_source = thumb if thumb.exists() else None

        # Blur detection — flag soft/out-of-focus shots for review
        if settings.blur_enabled and blur_source is not None:
            try:
                blur = detect_blur(blur_source, threshold=settings.blur_threshold)
                if blur is not None:
                    media.blur_score = blur.score
                    media.is_blurry = blur.is_blurry
                    if blur.is_blurry and settings.blur_auto_flag:
                        media.flag = True
                    log.info(
                        "blur_scored",
                        media_id=media.id,
                        score=blur.score,
                        is_blurry=blur.is_blurry,
                        threshold=blur.threshold,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("blur_detect_failed", media_id=media.id, error=str(exc))

        session.flush()

        try:
            analyse_media(session, media, settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("vlm_step_failed", media_id=media.id, error=str(exc))

        try:
            generate_embedding(session, media, settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("embedding_step_failed", media_id=media.id, error=str(exc))

        try:
            find_duplicates_for_media(session, media, settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("duplicate_step_failed", media_id=media.id, error=str(exc))

        try:
            upsert_fts(session, media, media.analysis)
        except Exception as exc:  # noqa: BLE001
            log.warning("fts_step_failed", media_id=media.id, error=str(exc))

        # Promote staging → immutable originals only after classification
        if promote and (media.lifecycle or "staging") == "staging":
            ok = _promote_media(session, media, settings, originals_root)
            if not ok:
                return "error"
        elif (media.lifecycle or "library") == "library":
            # Already in library (legacy path) — ensure HITL exists
            _ensure_hitl(session, media, settings)
        else:
            media.lifecycle = "library"
            _ensure_hitl(session, media, settings)

        log.info(
            "media_processed",
            media_id=media.id,
            filename=media.filename,
            lifecycle=media.lifecycle,
        )
        return "promoted" if promote else "ok"


def _promote_media(
    session,
    media: MediaItem,
    settings: Settings,
    originals_root: Path | None,
) -> bool:
    """Move file from staging into originals/ and open HITL."""
    src = Path(media.library_path)
    if not src.exists():
        return False

    if originals_root is None:
        # library/staging/{prov}/file → library/originals/by-provenance/{prov}/file
        # or keep parent name as provenance
        originals_root = settings.originals_dir / src.parent.name

    originals_root.mkdir(parents=True, exist_ok=True)
    dest = originals_root / src.name
    # Avoid clobber
    if dest.exists() and dest.resolve() != src.resolve():
        dest = originals_root / f"{media.id[:8]}_{src.name}"

    try:
        if src.resolve() != dest.resolve():
            shutil.move(str(src), str(dest))
        media.library_path = str(dest)
        media.lifecycle = "library"
        # AI decides — no HITL queue. Human can edit captions / trash later in Library.
        media.hitl_status = "accepted"
        media.updated_at = datetime.now(timezone.utc)
        _close_open_hitl(session, media, resolution="accepted")
        session.flush()
        log.info("media_promoted", media_id=media.id, dest=str(dest))
        return True
    except OSError as exc:
        log.error("promote_failed", media_id=media.id, error=str(exc))
        return False


def _close_open_hitl(session, media: MediaItem, *, resolution: str = "accepted") -> None:
    """Resolve any leftover HITL rows (legacy) so nothing sits in review."""
    now = datetime.now(timezone.utc)
    for item in (
        session.query(HitlQueueItem)
        .filter(HitlQueueItem.media_id == media.id, HitlQueueItem.resolved_at.is_(None))
        .all()
    ):
        item.resolved_at = now
        item.resolution = resolution


def _purge_rejected_media(
    session,
    media: MediaItem,
    settings: Settings,
    code: str | None,
    reason: str | None,
) -> None:
    """Remove junk from staging/library: quarantine, drop HITL, mark rejected."""
    path = Path(media.library_path)
    if path.exists() and settings.quality_quarantine_rejects:
        dest = settings.quarantine_dir / "pipeline" / f"{code or 'reject'}_{media.filename}"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
            media.library_path = str(dest)
        except OSError:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    elif path.exists():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    for d in (settings.thumbs_dir, settings.previews_dir):
        for p in d.glob(f"{media.id}.*"):
            p.unlink(missing_ok=True)

    media.hitl_status = "rejected"
    media.lifecycle = "rejected"
    media.quality_score = 0.0
    media.updated_at = datetime.now(timezone.utc)

    for item in (
        session.query(HitlQueueItem)
        .filter(HitlQueueItem.media_id == media.id, HitlQueueItem.resolved_at.is_(None))
        .all()
    ):
        item.resolved_at = datetime.now(timezone.utc)
        item.resolution = "rejected"
        item.queue_type = f"quality:{code or 'reject'}"

    if media.analysis is None:
        session.add(
            MediaAnalysis(
                media_id=media.id,
                caption_short=f"Auto-rejected: {code}",
                description=reason or "Failed quality gate",
                confidence=0.0,
                model_name="quality-gate",
                analysed_at=datetime.now(timezone.utc),
            )
        )
    else:
        media.analysis.caption_short = f"Auto-rejected: {code}"
        media.analysis.description = reason
