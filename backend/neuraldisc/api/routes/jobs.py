"""Job status, cancellation, and stale-job recovery endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from neuraldisc.db.database import get_db
from neuraldisc.db.models import Job
from neuraldisc.ingest.importer import get_import_progress, list_live_imports
from neuraldisc.jobs.control import (
    TERMINAL,
    live_worker_ids,
    reap_orphan_jobs,
    request_cancel,
)
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _enrich(job: Job) -> dict:
    """Attach live-worker / stale flags for the UI."""
    live = live_worker_ids()
    is_active = job.status in ("queued", "running")
    has_worker = job.id in live
    stale = is_active and not has_worker
    # Import-specific live progress if any
    live_prog = None
    if job.job_type == "import":
        p = get_import_progress(job.id)
        if p:
            live_prog = p.to_dict()
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "completed": job.completed,
        "message": job.message,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "has_live_worker": has_worker,
        "stale": stale,
        "live": live_prog,
    }


@router.get("")
def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
) -> list[dict]:
    # Opportunistic reap of clearly-orphan rows (not force-all; respects age + live set)
    try:
        reap_orphan_jobs(reason="lazy_reap", force_all_active=False)
    except Exception as exc:  # noqa: BLE001
        log.debug("lazy_reap_failed", error=str(exc))

    q = db.query(Job).order_by(Job.created_at.desc())
    if status:
        q = q.filter(Job.status == status)
    jobs = q.limit(limit).all()
    return [_enrich(j) for j in jobs]


@router.get("/live")
def jobs_live() -> dict:
    """In-memory workers currently attached to this process."""
    return {
        "workers": list_live_imports(),
        "worker_ids": sorted(live_worker_ids()),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/reap-stale")
def reap_stale_jobs(
    force: bool = Query(
        False,
        description=(
            "If true, same as only-orphans but reason=force_reap. "
            "Never closes jobs that still have a live worker in this process."
        ),
    ),
) -> dict:
    """Mark orphan/stale jobs (no live worker) as interrupted.

    Safe: does not delete library media. Does not cancel live workers.
    """
    # Manual clear: any active row without a worker, ignore age grace period
    result = reap_orphan_jobs(
        reason="force_reap" if force else "manual_reap",
        force_all_active=False,
        only_orphans=True,
    )
    # Immediately re-queue unfinished work so nothing sits idle
    try:
        from neuraldisc.jobs.supervisor import run_recovery_pass

        result["auto_resume"] = run_recovery_pass()
    except Exception as exc:  # noqa: BLE001
        log.debug("post_reap_auto_resume_failed", error=str(exc))
        result["auto_resume"] = []
    return result


@router.get("/supervisor")
def supervisor_status() -> dict:
    """Auto-resume supervisor state (staging / import / inference)."""
    from neuraldisc.ingest.staging_processor import get_process_state, staging_pending_count
    from neuraldisc.jobs.supervisor import get_supervisor_state

    return {
        "supervisor": get_supervisor_state(),
        "staging": get_process_state(),
        "staging_pending": staging_pending_count(),
    }


@router.post("/supervisor/tick")
def supervisor_tick() -> dict:
    """Force one auto-resume pass (manual nudge)."""
    from neuraldisc.jobs.supervisor import ensure_supervisor_running, run_recovery_pass

    ensure_supervisor_running()
    actions = run_recovery_pass()
    return {"ok": True, "actions": actions}


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _enrich(job)


@router.post("/{job_id}/resume")
def resume_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Resume an interrupted/failed/cancelled import (or re-queue post_ingest).

    Import resume: drain remaining staging files, then re-scan sources skipping
    SHA-256 duplicates already in the library.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.job_type == "import":
        try:
            from neuraldisc.ingest.importer import resume_import

            # Detach before background thread uses other sessions
            jid = resume_import(job_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("resume_import_failed", job_id=job_id)
            raise HTTPException(500, f"Resume failed: {exc}") from exc
        db.expire_all()
        job = db.get(Job, jid)
        return {
            "ok": True,
            "job_id": jid,
            "message": "Import resume started",
            "job": _enrich(job) if job else None,
        }

    if job.job_type == "post_ingest":
        try:
            payload = json.loads(job.payload or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        disc_id = payload.get("disc_id")
        if not disc_id:
            raise HTTPException(400, "post_ingest job missing disc_id")
        if job.status in ("running", "queued") and job_id in live_worker_ids():
            raise HTTPException(400, "Job is still running")
        # Spawn process_disc in a thread
        import threading
        from neuraldisc.processing.pipeline import process_disc
        from neuraldisc.jobs.control import register_job, clear_cancel

        job.status = "queued"
        job.error = None
        job.finished_at = None
        job.message = "Resume post-ingest queued"
        db.commit()
        clear_cancel(job_id)
        register_job(job_id)

        def _run() -> None:
            try:
                process_disc(disc_id, job_id=job_id)
            finally:
                clear_cancel(job_id)

        threading.Thread(
            target=_run, name=f"resume-post-{job_id[:8]}", daemon=True
        ).start()
        db.refresh(job)
        return {
            "ok": True,
            "job_id": job_id,
            "message": "Post-ingest resume started",
            "job": _enrich(job),
        }

    if job.job_type == "inference":
        raise HTTPException(
            400,
            "Inference jobs: use POST /api/inference/run to start a new batch",
        )

    raise HTTPException(400, f"Cannot resume job type {job.job_type}")


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    force: bool = Query(
        False,
        description="Force-close immediately (second click / stuck Cancelling…)",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Request cooperative cancellation of a running/queued job.

    If no live worker exists (stale after restart), the job is closed immediately.
    Pass ``force=true`` (or cancel twice) to finalize a stuck Cancelling… import.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in TERMINAL:
        raise HTTPException(400, f"Job already {job.status}")

    result = request_cancel(job_id, force=force)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Cannot cancel job")
    db.expire_all()
    job = db.get(Job, job_id)
    return {
        **result,
        "job": _enrich(job) if job else None,
    }
