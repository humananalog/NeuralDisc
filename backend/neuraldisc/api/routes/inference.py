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


def _is_heuristic(
    model_name: str | None, model_version: str | None = None
) -> bool:
    if not model_name:
        return True
    m = model_name.lower()
    v = (model_version or "").lower()
    return (
        "heuristic" in m
        or m in ("quality-gate", "none", "")
        or "vlm-failed" in m
        or "vlm-failed" in v
        or "vlm-gave-up" in v
        or m.endswith(":failed")
    )


def _heuristic_filter(*, include_gave_up: bool = False):
    """SQL filter: analysis that is not real VLM (failed / never ran).

    ``vlm-gave-up`` is excluded from auto-chain/supervisor by default so
    persistent parse/OOM failures cannot spawn infinite jobs.
    """
    from sqlalchemy import and_, not_

    clauses = [
        MediaAnalysis.model_name.is_(None),
        MediaAnalysis.model_name == "",
        MediaAnalysis.model_name.ilike("%heuristic%"),
        MediaAnalysis.model_name.ilike("%quality-gate%"),
        MediaAnalysis.model_name.ilike("%vlm-failed%"),
        MediaAnalysis.model_version.ilike("%vlm-failed%"),
    ]
    if include_gave_up:
        clauses.append(MediaAnalysis.model_version.ilike("%vlm-gave-up%"))
    filt = or_(*clauses)
    if not include_gave_up:
        filt = and_(filt, not_(MediaAnalysis.model_version.ilike("%vlm-gave-up%")))
    return filt


def collect_inference_queue_ids(
    db: Session,
    *,
    limit: int = 100,
    force_heuristic: bool = True,
    include_gave_up: bool = False,
) -> list[str]:
    """All library items that still need real VLM (pending or failed→heuristic)."""
    limit = max(1, min(int(limit), 5000))
    ids: list[str] = []
    seen: set[str] = set()

    # 1) Never analysed
    pending = (
        db.query(MediaItem.id)
        .outerjoin(MediaAnalysis, MediaAnalysis.media_id == MediaItem.id)
        .filter(_lib_filter(), MediaAnalysis.media_id.is_(None))
        .order_by(MediaItem.created_at.asc())
        .limit(limit)
        .all()
    )
    for (mid,) in pending:
        if mid not in seen:
            seen.add(mid)
            ids.append(mid)

    if force_heuristic and len(ids) < limit:
        need = limit - len(ids)
        heuristic = (
            db.query(MediaItem.id)
            .join(MediaAnalysis, MediaAnalysis.media_id == MediaItem.id)
            .filter(_lib_filter(), _heuristic_filter(include_gave_up=include_gave_up))
            .order_by(MediaItem.created_at.asc())
            .limit(need)
            .all()
        )
        for (mid,) in heuristic:
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)

    return ids[:limit]


def count_inference_queue(
    db: Session, *, force_heuristic: bool = True, include_gave_up: bool = False
) -> dict[str, int]:
    pending = (
        db.query(func.count(MediaItem.id))
        .outerjoin(MediaAnalysis, MediaAnalysis.media_id == MediaItem.id)
        .filter(_lib_filter(), MediaAnalysis.media_id.is_(None))
        .scalar()
        or 0
    )
    heuristic = 0
    if force_heuristic:
        heuristic = (
            db.query(func.count(MediaItem.id))
            .join(MediaAnalysis, MediaAnalysis.media_id == MediaItem.id)
            .filter(_lib_filter(), _heuristic_filter(include_gave_up=include_gave_up))
            .scalar()
            or 0
        )
    return {
        "pending": int(pending),
        "heuristic": int(heuristic),
        "queue": int(pending) + int(heuristic),
    }


def start_inference_job(
    media_ids: list[str],
    *,
    force_heuristic: bool = True,
    reason: str = "manual",
) -> dict:
    """Create + start an inference job for the given media ids."""
    if not media_ids:
        return {"job_id": None, "queued": 0, "message": "Nothing pending for inference"}

    settings = get_settings()
    with session_scope() as session:
        job = Job(
            job_type="inference",
            status="queued",
            message=f"Inference queue: {len(media_ids)} items ({reason})",
            total=len(media_ids),
            completed=0,
            progress=0.0,
            payload=json.dumps(
                {
                    "media_ids": media_ids,
                    "force_heuristic": force_heuristic,
                    "reason": reason,
                }
            ),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    register_job(job_id)
    t = threading.Thread(
        target=_run_inference_job,
        args=(job_id, media_ids),
        name=f"neuraldisc-infer-{job_id[:8]}",
        daemon=True,
    )
    t.start()
    log.info(
        "inference_job_started",
        job_id=job_id,
        n=len(media_ids),
        reason=reason,
    )
    return {
        "job_id": job_id,
        "queued": len(media_ids),
        "message": f"Started inference on {len(media_ids)} items",
        "vlm_enabled": settings.vlm_enabled,
        "reason": reason,
    }


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
    counts = count_inference_queue(
        db, force_heuristic=bool(settings.vlm_enabled)
    )
    heuristic = counts["heuristic"]
    pending = counts["pending"]
    vlm_done = (
        db.query(func.count(MediaAnalysis.media_id))
        .join(MediaItem, MediaItem.id == MediaAnalysis.media_id)
        .filter(
            _lib_filter(),
            MediaAnalysis.model_name.isnot(None),
            ~MediaAnalysis.model_name.ilike("%heuristic%"),
            ~MediaAnalysis.model_name.ilike("%quality-gate%"),
            ~MediaAnalysis.model_name.ilike("%vlm-failed%"),
        )
        .scalar()
        or 0
    )
    # Queue = no analysis, or heuristic / failed VLM while VLM is enabled
    queue_n = counts["queue"] if settings.vlm_enabled else pending

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
        if _is_heuristic(m.analysis.model_name, m.analysis.model_version):
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
                        if _is_heuristic(
                            m.analysis.model_name, m.analysis.model_version
                        )
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
        True,
        description="Re-run heuristic / failed-VLM items (default true)",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Start a background job to analyse pending and failed/heuristic items."""
    settings = get_settings()
    # Avoid stacking concurrent inference workers
    active = (
        db.query(Job)
        .filter(Job.job_type == "inference", Job.status.in_(("queued", "running")))
        .first()
    )
    if active:
        return {
            "job_id": active.id,
            "queued": 0,
            "message": f"Inference already {active.status}: {active.message or active.id[:8]}",
            "vlm_enabled": settings.vlm_enabled,
            "already_running": True,
        }

    ids = collect_inference_queue_ids(
        db, limit=limit, force_heuristic=force_heuristic
    )
    return start_inference_job(
        ids, force_heuristic=force_heuristic, reason="manual"
    )


@router.post("/requeue-heuristic")
def requeue_all_heuristic(
    limit: int = Query(
        500,
        ge=1,
        le=5000,
        description="Max items in this batch (remaining stay queued for next auto pass)",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Re-queue every library item still on heuristic / failed VLM for real inference."""
    settings = get_settings()
    if not settings.vlm_enabled:
        raise HTTPException(
            400,
            "VLM is disabled — enable VLM in Settings before re-queuing heuristics",
        )
    active = (
        db.query(Job)
        .filter(Job.job_type == "inference", Job.status.in_(("queued", "running")))
        .first()
    )
    if active:
        counts = count_inference_queue(db, force_heuristic=True)
        return {
            "job_id": active.id,
            "queued": 0,
            "remaining": counts["queue"],
            "message": f"Inference already running — {counts['queue']} still need VLM",
            "already_running": True,
        }

    counts = count_inference_queue(db, force_heuristic=True)
    ids = collect_inference_queue_ids(db, limit=limit, force_heuristic=True)
    res = start_inference_job(
        ids, force_heuristic=True, reason="requeue-heuristic"
    )
    res["remaining_after"] = max(0, counts["queue"] - len(ids))
    res["total_queue"] = counts["queue"]
    res["message"] = (
        f"Re-queued {len(ids)} of {counts['queue']} heuristic/failed items"
        + (
            f" · {res['remaining_after']} left for next batch"
            if res.get("remaining_after")
            else ""
        )
    )
    return res


def _run_inference_job(job_id: str, media_ids: list[str]) -> None:
    settings = get_settings()
    done = 0
    errors = 0
    chain_next = False
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
        chain_next = True
    except Exception as exc:  # noqa: BLE001
        log.exception("inference_job_failed", job_id=job_id)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job and job.status in ("queued", "running"):
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(timezone.utc)
                job.message = f"Failed: {exc}"
        chain_next = True
    finally:
        # Always free GPU/unified memory for peer apps (mlx_lm :8088, etc.)
        try:
            rel = release_vlm(force=True)
            log.info("inference_job_mlx_released", job_id=job_id, **rel)
        except Exception as rel_exc:  # noqa: BLE001
            log.warning("inference_job_release_failed", error=str(rel_exc))
        clear_cancel(job_id)
        # After release, continue draining heuristic/failed queue
        if chain_next:
            try:
                _chain_remaining_inference(previous_ids=media_ids)
            except Exception as chain_exc:  # noqa: BLE001
                log.warning("inference_chain_failed", error=str(chain_exc))


def _chain_remaining_inference(*, previous_ids: list[str] | None = None) -> None:
    """If VLM is on and heuristics remain, start the next batch immediately.

    Stops when the only remaining IDs were just processed (persistent failures)
    so we do not spawn infinite identical jobs.
    """
    settings = get_settings()
    if not settings.vlm_enabled:
        return
    if not settings.auto_resume_inference:
        return
    with session_scope() as session:
        active = (
            session.query(Job.id)
            .filter(
                Job.job_type == "inference",
                Job.status.in_(("queued", "running")),
            )
            .first()
        )
        if active:
            return
        remaining = count_inference_queue(session, force_heuristic=True)["queue"]
        if remaining <= 0:
            log.info("inference_queue_drained")
            return
        batch = min(settings.auto_resume_inference_limit, 100)
        ids = collect_inference_queue_ids(
            session, limit=batch, force_heuristic=True
        )
    if not ids:
        return
    prev = set(previous_ids or [])
    if prev and set(ids).issubset(prev):
        log.info(
            "inference_chain_stopped_no_progress",
            remaining=remaining,
            batch=len(ids),
        )
        return
    log.info("inference_chain_next", remaining=remaining, batch=len(ids))
    start_inference_job(ids, force_heuristic=True, reason="chain")
