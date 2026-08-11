"""Cooperative job cancellation + stale-job recovery.

Background threads check ``is_cancel_requested(job_id)`` between work units.
``request_cancel`` marks the Job row and any in-memory import progress.

Jobs are in-process (threads). On API restart they leave SQLite rows stuck in
``running`` / ``queued``. ``reap_orphan_jobs`` closes those as ``interrupted``.

Workers must call ``register_job`` when they start and ``clear_cancel`` (or
``unregister_job``) when they finish so the UI can distinguish live vs orphan.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Job
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_CANCEL: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()

# Job ids with an attached in-process worker thread (any job type)
_LIVE_WORKERS: set[str] = set()
_LIVE_LOCK = threading.Lock()

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
ACTIVE = frozenset({"queued", "running"})

# Lazy list-endpoint reap only: old running jobs with no worker
STALE_RUNNING_AFTER = timedelta(minutes=15)
# Queued jobs never picked up
STALE_QUEUED_AFTER = timedelta(minutes=10)


def _event(job_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        ev = _CANCEL.get(job_id)
        if ev is None:
            ev = threading.Event()
            _CANCEL[job_id] = ev
        return ev


def register_job(job_id: str) -> threading.Event:
    """Mark job as having a live worker and ensure a cancel event exists."""
    with _LIVE_LOCK:
        _LIVE_WORKERS.add(job_id)
    return _event(job_id)


def unregister_job(job_id: str) -> None:
    """Drop live-worker registration (job finished or failed)."""
    with _LIVE_LOCK:
        _LIVE_WORKERS.discard(job_id)


def is_cancel_requested(job_id: str | None) -> bool:
    if not job_id:
        return False
    with _CANCEL_LOCK:
        ev = _CANCEL.get(job_id)
    return bool(ev and ev.is_set())


def live_worker_ids() -> set[str]:
    """Job ids that still have an in-process worker.

    Combines explicit ``register_job`` registry (inference, post_ingest, import)
    with the import progress map as a belt-and-braces fallback.
    """
    with _LIVE_LOCK:
        live = set(_LIVE_WORKERS)
    try:
        from neuraldisc.ingest.importer import list_live_imports

        for p in list_live_imports():
            st = p.get("status")
            if st not in ("completed", "failed", "cancelled", "interrupted"):
                jid = p.get("job_id")
                if jid:
                    live.add(jid)
    except Exception:  # noqa: BLE001
        pass
    return live


def request_cancel(job_id: str, *, force: bool = False) -> dict:
    """Request cancellation. Returns status dict for the API.

    ``force=True`` (or a second cancel while already Cancelling…) closes the
    job immediately even if a worker is still draining — used when UI is stuck.
    """
    ev = _event(job_id)
    already = ev.is_set()
    ev.set()

    # Import progress flag (if live)
    try:
        from neuraldisc.ingest.importer import mark_import_cancelled, force_cancel_import

        if force or already:
            # Second click / explicit force → leave Cancelling… now
            force_cancel_import(job_id)
            return {
                "job_id": job_id,
                "ok": True,
                "status": "cancelled",
                "cancel_requested": True,
                "already_requested": already,
                "forced": True,
                "message": "Cancelled",
            }
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
        if job.status in TERMINAL and not already:
            return {
                "job_id": job_id,
                "ok": False,
                "error": f"Job already {job.status}",
                "status": job.status,
            }
        if job.status in ACTIVE or job.status not in TERMINAL:
            live = live_worker_ids()
            was_queued = job.status == "queued"
            has_worker = job_id in live
            if was_queued or not has_worker:
                # No in-process worker can finish this job — close now
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc)
                job.error = "cancelled_by_user"
                if was_queued:
                    job.message = "Cancelled before start"
                else:
                    job.message = (
                        "Cancelled — worker no longer running (stale after restart)"
                    )
                unregister_job(job_id)
            else:
                # Soft mark: live worker will flip to cancelled when it notices
                if "cancel" not in (job.message or "").lower():
                    job.message = "Cancel requested…"
        job_status = job.status
        log.info("job_cancel_requested", job_id=job_id, status=job_status)

    return {
        "job_id": job_id,
        "ok": True,
        "status": job_status,
        "cancel_requested": True,
        "already_requested": already,
        "forced": False,
        "message": "Cancellation requested" if not already else "Cancel already requested",
    }


def mark_cancelled(job_id: str, message: str = "Cancelled by user") -> None:
    """Worker-side: mark job fully cancelled after stopping work."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job:
            unregister_job(job_id)
            return
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        job.message = message
        job.error = job.error or "cancelled_by_user"
        log.info("job_cancelled", job_id=job_id)
    unregister_job(job_id)


def clear_cancel(job_id: str) -> None:
    """Drop cancel event + live registration after job ends."""
    unregister_job(job_id)
    with _CANCEL_LOCK:
        _CANCEL.pop(job_id, None)


def reap_orphan_jobs(
    *,
    reason: str = "interrupted",
    force_all_active: bool = False,
    only_orphans: bool = False,
    max_running_age: timedelta | None = None,
    max_queued_age: timedelta | None = None,
) -> dict:
    """Close jobs that have no live worker (API restart / crash).

    ``force_all_active=True`` — process startup: every queued/running row is
    orphaned (previous process is gone).

    ``only_orphans=True`` — manual Clear/Reap: close any active job with no
    live worker, ignoring age (does **not** touch jobs with live workers).

    Default (lazy list): only reaps when older than age thresholds *and*
    not in the live worker registry.
    """
    now = datetime.now(timezone.utc)
    max_running_age = max_running_age or STALE_RUNNING_AFTER
    max_queued_age = max_queued_age or STALE_QUEUED_AFTER
    live = set() if force_all_active else live_worker_ids()

    reaped: list[dict] = []
    with session_scope() as session:
        active = (
            session.query(Job)
            .filter(Job.status.in_(("queued", "running")))
            .order_by(Job.created_at.asc())
            .all()
        )
        for job in active:
            if job.id in live:
                continue
            if not force_all_active and not only_orphans:
                created = job.created_at or now
                started = job.started_at or created
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if job.status == "queued" and now - created < max_queued_age:
                    continue
                if job.status == "running" and now - started < max_running_age:
                    continue

            prev = job.status
            done = job.completed or 0
            total = job.total or 0
            # If user had already asked to cancel, don't revive as "interrupted"
            # (supervisor would auto-resume and recreate Cancelling… limbo).
            user_cancel = "cancel" in (job.message or "").lower() or (
                job.error == "cancelled_by_user"
            )
            if user_cancel:
                job.status = "cancelled"
                job.error = "cancelled_by_user"
                job.message = (
                    f"Cancelled ({reason}). Was {prev} at {done}/{total}."
                )
            else:
                job.status = "interrupted"
                job.error = reason
                if job.job_type == "inference":
                    job.message = (
                        f"Interrupted: {reason}. "
                        f"Was {prev} at {done}/{total} analysed. "
                        "Safe to re-run inference; already-analysed items are kept."
                    )
                else:
                    job.message = (
                        f"Interrupted: {reason}. "
                        f"Was {prev} at {done}/{total}. "
                        "Safe to re-run import; already-promoted library items are kept."
                    )
            job.finished_at = now
            reaped.append(
                {
                    "id": job.id,
                    "job_type": job.job_type,
                    "was": prev,
                    "completed": done,
                    "total": total,
                    "final": job.status,
                }
            )
            # Stop any zombie thread that might still be looping
            _event(job.id).set()
            unregister_job(job.id)
            log.warning(
                "job_reaped",
                job_id=job.id,
                job_type=job.job_type,
                was=prev,
                reason=reason,
            )

    return {
        "reaped": reaped,
        "count": len(reaped),
        "reason": reason,
        "live_workers": sorted(live),
    }


def recover_jobs_on_startup() -> dict:
    """Call from API lifespan — no prior process workers can still be running."""
    with _LIVE_LOCK:
        _LIVE_WORKERS.clear()
    with _CANCEL_LOCK:
        _CANCEL.clear()
    result = reap_orphan_jobs(
        reason="api_restart",
        force_all_active=True,
    )
    if result["count"]:
        log.warning(
            "startup_jobs_recovered",
            count=result["count"],
            ids=[r["id"][:8] for r in result["reaped"]],
        )
    else:
        log.info("startup_jobs_clean")
    return result
