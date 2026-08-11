"""Inference status, queue, and batch re-analysis."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from neuraldisc.api.serializers import media_to_out
from neuraldisc.ai.vlm import reanalyse_media, release_vlm, vlm_session, vlm_status
from neuraldisc.config import get_settings
from neuraldisc.db.database import get_db, session_scope
from neuraldisc.db.models import Job, MediaAnalysis, MediaItem
from neuraldisc.jobs.control import register_job, clear_cancel, is_cancel_requested
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])


def _lib_filter():
    return or_(MediaItem.lifecycle == "library", MediaItem.lifecycle.is_(None))


def _is_heuristic(model_name: str | None) -> bool:
    if not model_name:
        return True
    m = model_name.lower()
    return "heuristic" in m or m in ("quality-gate", "none", "")


@router.get("/status")
def inference_status(db: Session = Depends(get_db)) -> dict:
    """Overview of VLM / analysis coverage for library media."""
    settings = get_settings()
    total = db.query(func.count(MediaItem.id)).filter(_lib_filter()).scalar() or 0
    with_analysis = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(_lib_filter())
        .scalar()
        or 0
    )
    heuristic = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(
            _lib_filter(),
            or_(
                MediaAnalysis.model_name.is_(None),
                MediaAnalysis.model_name.ilike("%heuristic%"),
            ),
        )
        .scalar()
        or 0
    )
    vlm_done = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(
            _lib_filter(),
            MediaAnalysis.model_name.isnot(None),
            ~MediaAnalysis.model_name.ilike("%heuristic%"),
        )
        .scalar()
        or 0
    )
    pending = total - with_analysis
    # Queue = no analysis, or heuristic while VLM is enabled
    queue_n = pending + (heuristic if settings.vlm_enabled else 0)

    active_job = (
        db.query(Job)
        .filter(Job.job_type == "inference", Job.status.in_(("queued", "running")))
        .order_by(Job.created_at.desc())
        .first()
    )

    vlm = vlm_status(settings)
    return {
        "vlm_enabled": settings.vlm_enabled,
        "vlm_model": settings.vlm_model,
        "total_library": total,
        "with_analysis": with_analysis,
        "pending": pending,  # never analysed
        "heuristic": heuristic,
        "vlm_done": vlm_done,
        "queue": queue_n,  # items that would be (re)processed
        "coverage_pct": round(100.0 * with_analysis / total, 1) if total else 0.0,
        "vlm_pct": round(100.0 * vlm_done / total, 1) if total else 0.0,
        "vlm_loaded": vlm.get("loaded", False),
        "vlm_refcount": vlm.get("refcount", 0),
        "metal": vlm.get("metal") or {},
        "active_job": (
            {
                "id": active_job.id,
                "status": active_job.status,
                "progress": active_job.progress,
                "completed": active_job.completed,
                "total": active_job.total,
                "message": active_job.message,
            }
            if active_job
            else None
        ),
    }


@router.post("/release")
def release_mlx_plane() -> dict:
    """Unload VLM weights and clear MLX Metal cache for other apps (e.g. :8088)."""
    return release_vlm(force=True)


@router.get("/queue")
def inference_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = Query(
        "pending",
        description="pending = no analysis; heuristic = fallback only; all = either",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Media waiting for (or eligible for) VLM analysis."""
    settings = get_settings()
    q = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(_lib_filter())
        .order_by(MediaItem.created_at.desc())
    )
    items = q.offset(0).limit(5000).all()  # filter in Python for clarity

    def eligible(m: MediaItem) -> bool:
        if m.analysis is None:
            return mode in ("pending", "all")
        if _is_heuristic(m.analysis.model_name):
            return mode in ("heuristic", "all") or (
                mode == "pending" and settings.vlm_enabled
            )
        return False

    filtered = [m for m in items if eligible(m)]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "mode": mode,
        "items": [
            {
                **media_to_out(m, settings).model_dump(mode="json"),
                "inference_state": (
                    "pending"
                    if m.analysis is None
                    else (
                        "heuristic"
                        if _is_heuristic(m.analysis.model_name)
                        else "vlm"
                    )
                ),
            }
            for m in page
        ],
    }


@router.post("/{media_id}/reanalyse")
def reanalyse_one(
    media_id: str,
    keep_loaded: bool = Query(
        False,
        description="If false (default), unload VLM / clear MLX after this item",
    ),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    media = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(MediaItem.id == media_id)
        .first()
    )
    if not media:
        raise HTTPException(404, "Media not found")
    try:
        with vlm_session(release_on_exit=not keep_loaded):
            analysis = reanalyse_media(db, media, settings)
        db.commit()
        db.refresh(media)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if not keep_loaded:
            release_vlm(force=True)
        raise HTTPException(500, f"Reanalyse failed: {exc}") from exc
    return {
        "media_id": media_id,
        "ok": analysis is not None,
        "model_name": analysis.model_name if analysis else None,
        "media": media_to_out(media, settings),
        "vlm_released": not keep_loaded,
    }


@router.post("/run")
def run_inference_batch(
    limit: int = Query(100, ge=1, le=2000),
    force_heuristic: bool = Query(
        False,
        description="Also re-run items that only have heuristic analysis",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Start a background job to analyse pending (and optionally heuristic) items."""
    settings = get_settings()

    # Collect ids
    q = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(_lib_filter())
        .order_by(MediaItem.created_at.asc())
    )
    ids: list[str] = []
    for m in q.limit(limit * 3).all():
        if m.analysis is None:
            ids.append(m.id)
        elif force_heuristic and _is_heuristic(m.analysis.model_name):
            ids.append(m.id)
        if len(ids) >= limit:
            break

    if not ids:
        return {"job_id": None, "queued": 0, "message": "Nothing pending for inference"}

    job = Job(
        job_type="inference",
        status="queued",
        message=f"Inference queue: {len(ids)} items",
        total=len(ids),
        completed=0,
        progress=0.0,
        payload=json.dumps({"media_ids": ids, "force_heuristic": force_heuristic}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    register_job(job_id)

    t = threading.Thread(
        target=_run_inference_job,
        args=(job_id, ids),
        name=f"neuraldisc-infer-{job_id[:8]}",
        daemon=True,
    )
    t.start()
    log.info("inference_job_started", job_id=job_id, n=len(ids))
    return {
        "job_id": job_id,
        "queued": len(ids),
        "message": f"Started inference on {len(ids)} items",
        "vlm_enabled": settings.vlm_enabled,
    }


def _run_inference_job(job_id: str, media_ids: list[str]) -> None:
    settings = get_settings()
    done = 0
    errors = 0
    try:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job:
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.message = f"Analysing 0/{len(media_ids)}"

        # Hold VLM for the whole batch; release_vlm() on exit frees MLX for other apps
        with vlm_session(release_on_exit=True):
            for mid in media_ids:
                if is_cancel_requested(job_id):
                    with session_scope() as session:
                        job = session.get(Job, job_id)
                        # Don't clobber reap → interrupted
                        if job and job.status in ("queued", "running"):
                            job.status = "cancelled"
                            job.finished_at = datetime.now(timezone.utc)
                            job.message = f"Cancelled after {done}/{len(media_ids)}"
                            job.error = "cancelled_by_user"
                    return

                try:
                    with session_scope() as session:
                        media = (
                            session.query(MediaItem)
                            .options(joinedload(MediaItem.analysis))
                            .filter(MediaItem.id == mid)
                            .first()
                        )
                        if media:
                            reanalyse_media(session, media, settings)
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    log.warning("inference_item_failed", media_id=mid, error=str(exc))

                with session_scope() as session:
                    job = session.get(Job, job_id)
                    if not job:
                        return
                    # Stop if reaped / cancelled / failed externally
                    if job.status not in ("queued", "running"):
                        return
                    job.completed = done
                    job.total = len(media_ids)
                    job.progress = done / max(len(media_ids), 1)
                    job.message = (
                        f"Analysed {done}/{len(media_ids)}"
                        + (f" · {errors} errors" if errors else "")
                    )

        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status in ("queued", "running"):
                job.status = "completed"
                job.finished_at = datetime.now(timezone.utc)
                job.progress = 1.0
                job.completed = done
                job.message = (
                    f"Done: {done} analysed"
                    + (f", {errors} errors" if errors else "")
                    + " · MLX released"
                )
    except Exception as exc:  # noqa: BLE001
        log.exception("inference_job_failed", job_id=job_id)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status in ("queued", "running"):
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(timezone.utc)
                job.message = f"Failed: {exc}"
    finally:
        # Always free GPU/unified memory for peer apps (mlx_lm :8088, etc.)
        try:
            rel = release_vlm(force=True)
            log.info("inference_job_mlx_released", job_id=job_id, **rel)
        except Exception as rel_exc:  # noqa: BLE001
            log.warning("inference_job_release_failed", error=str(rel_exc))
        clear_cancel(job_id)
