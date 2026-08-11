"""Job status and cancellation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from neuraldisc.api.schemas import JobOut
from neuraldisc.db.database import get_db
from neuraldisc.db.models import Job
from neuraldisc.jobs.control import request_cancel

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(limit: int = 50, db: Session = Depends(get_db)) -> list[Job]:
    return db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Request cooperative cancellation of a running/queued job.

    Import and post-ingest workers stop between work units and mark the job
    ``cancelled``. Already-finished jobs return 400.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(400, f"Job already {job.status}")

    result = request_cancel(job_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Cannot cancel job")
    # Refresh
    db.refresh(job)
    return {
        **result,
        "job": {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "message": job.message,
            "progress": job.progress,
            "completed": job.completed,
            "total": job.total,
        },
    }
