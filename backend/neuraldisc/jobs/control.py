"""Cooperative job cancellation.

Background threads check ``is_cancel_requested(job_id)`` between work units.
``request_cancel`` marks the Job row and any in-memory import progress.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Job
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_CANCEL: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()


def _event(job_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        ev = _CANCEL.get(job_id)
        if ev is None:
            ev = threading.Event()
            _CANCEL[job_id] = ev
        return ev


def register_job(job_id: str) -> threading.Event:
    """Ensure a cancel event exists for a newly started job."""
    return _event(job_id)


def is_cancel_requested(job_id: str | None) -> bool:
    if not job_id:
        return False
    with _CANCEL_LOCK:
        ev = _CANCEL.get(job_id)
    return bool(ev and ev.is_set())


def request_cancel(job_id: str) -> dict:
    """Request cancellation. Returns status dict for the API."""
    ev = _event(job_id)
    already = ev.is_set()
    ev.set()

    # Import progress flag (if live)
    try:
        from neuraldisc.ingest.importer import mark_import_cancelled

        mark_import_cancelled(job_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("import_cancel_hook_failed", error=str(exc))

    job_status = None
    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job:
            return {
                "job_id": job_id,
                "ok": False,
                "error": "Job not found",
                "status": None,
            }
        terminal = job.status in ("completed", "failed", "cancelled")
        if terminal and not already:
            return {
                "job_id": job_id,
                "ok": False,
                "error": f"Job already {job.status}",
                "status": job.status,
            }
        if job.status in ("queued", "running") or job.status not in (
            "completed",
            "failed",
            "cancelled",
        ):
            # Soft mark: worker will flip to cancelled when it notices
            job.message = (job.message or "") + " · cancel requested"
            if "cancel" not in (job.message or "").lower():
                job.message = "Cancel requested…"
            # If still queued and never started, finish immediately
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc)
                job.message = "Cancelled before start"
                job.error = "cancelled_by_user"
        job_status = job.status
        log.info("job_cancel_requested", job_id=job_id, status=job_status)

    return {
        "job_id": job_id,
        "ok": True,
        "status": job_status,
        "cancel_requested": True,
        "already_requested": already,
        "message": "Cancellation requested" if not already else "Cancel already requested",
    }


def mark_cancelled(job_id: str, message: str = "Cancelled by user") -> None:
    """Worker-side: mark job fully cancelled after stopping work."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job:
            return
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        job.message = message
        job.error = job.error or "cancelled_by_user"
        log.info("job_cancelled", job_id=job_id)


def clear_cancel(job_id: str) -> None:
    """Drop cancel event after job ends (optional cleanup)."""
    with _CANCEL_LOCK:
        _CANCEL.pop(job_id, None)
