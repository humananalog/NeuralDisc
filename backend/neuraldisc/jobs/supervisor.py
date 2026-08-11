"""Auto-resume supervisor — no unfinished work left idle.

After API restart (or whenever workers die), this keeps:

  1. Staging processor alive while lifecycle=staging rows remain
  2. Interrupted/failed **import** jobs auto-resumed (serial, one at a time)
  3. Interrupted **post_ingest** re-queued when staging/library needs it
  4. Optional **inference** batches when VLM is on and the queue is non-empty

A single daemon thread ticks on an interval; every action is idempotent and
refuses to start duplicate live workers.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import joinedload

from neuraldisc.config import Settings, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Job, MediaAnalysis, MediaItem
from neuraldisc.jobs.control import live_worker_ids
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "status": "stopped",
    "last_tick": None,
    "last_actions": [],
    "ticks": 0,
}
_LAST_INFERENCE_AUTO: float = 0.0
_INFERENCE_COOLDOWN_SEC = 120.0


def get_supervisor_state() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def ensure_supervisor_running(settings: Settings | None = None) -> None:
    global _THREAD
    settings = settings or get_settings()
    if not settings.auto_resume_enabled:
        log.info("auto_resume_disabled")
        return
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_supervisor_loop,
            args=(settings,),
            name="neuraldisc-auto-resume",
            daemon=True,
        )
        _THREAD.start()
        _STATE["status"] = "running"
        log.info(
            "auto_resume_supervisor_started",
            interval=settings.auto_resume_interval_sec,
        )


def stop_supervisor(*, timeout: float = 3.0) -> None:
    _STOP.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=timeout)
    with _LOCK:
        _STATE["status"] = "stopped"


def run_recovery_pass(settings: Settings | None = None) -> list[str]:
    """One-shot recovery (startup + each watchdog tick). Returns action log lines."""
    settings = settings or get_settings()
    actions: list[str] = []
    if not settings.auto_resume_enabled:
        return actions

    # 1) Staging drain — always
    try:
        from neuraldisc.ingest.staging_processor import (
            ensure_processor_running,
            staging_pending_count,
            wake_processor,
        )

        pending = staging_pending_count()
        ensure_processor_running(settings)
        if pending > 0:
            wake_processor()
            actions.append(f"staging_wake pending={pending}")
    except Exception as exc:  # noqa: BLE001
        log.warning("supervisor_staging_failed", error=str(exc))
        actions.append(f"staging_error: {exc}")

    live = live_worker_ids()

    # 2) Auto-resume imports (serial — only if no live import worker)
    if settings.auto_resume_imports and not _has_live_import(live):
        try:
            resumed = _auto_resume_import(settings)
            if resumed:
                actions.append(f"import_resume {resumed[:8]}")
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor_import_resume_failed", error=str(exc))
            actions.append(f"import_error: {exc}")

    # 3) Post-ingest interrupted
    if settings.auto_resume_imports and not _has_live_job_type(live, "post_ingest"):
        try:
            pid = _auto_resume_post_ingest()
            if pid:
                actions.append(f"post_ingest_resume {pid[:8]}")
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor_post_ingest_failed", error=str(exc))

    # 4) Inference queue (VLM on, no live inference worker)
    if (
        settings.auto_resume_inference
        and settings.vlm_enabled
        and not _has_live_job_type(live, "inference")
        and not _has_active_inference_job()
    ):
        try:
            n = _auto_start_inference(settings)
            if n:
                actions.append(f"inference_start n={n}")
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor_inference_failed", error=str(exc))
            actions.append(f"inference_error: {exc}")

    return actions


def _supervisor_loop(settings: Settings) -> None:
    interval = max(10, int(settings.auto_resume_interval_sec))
    # Immediate pass so restart never idles
    try:
        actions = run_recovery_pass(settings)
        _record_tick(actions)
        if actions:
            log.info("auto_resume_startup", actions=actions)
    except Exception as exc:  # noqa: BLE001
        log.exception("auto_resume_startup_failed", error=str(exc))

    while not _STOP.is_set():
        _STOP.wait(timeout=interval)
        if _STOP.is_set():
            break
        try:
            # Refresh settings each tick (VLM may be toggled)
            settings = get_settings()
            if not settings.auto_resume_enabled:
                continue
            actions = run_recovery_pass(settings)
            _record_tick(actions)
            if actions:
                log.info("auto_resume_tick", actions=actions)
        except Exception as exc:  # noqa: BLE001
            log.exception("auto_resume_tick_failed", error=str(exc))


def _record_tick(actions: list[str]) -> None:
    with _LOCK:
        _STATE["last_tick"] = datetime.now(timezone.utc).isoformat()
        _STATE["last_actions"] = actions[-20:]
        _STATE["ticks"] = int(_STATE.get("ticks") or 0) + 1
        _STATE["status"] = "running"


def _has_live_import(live: set[str]) -> bool:
    if not live:
        return False
    with session_scope() as session:
        for jid in live:
            job = session.get(Job, jid)
            if job and job.job_type == "import" and job.status in ("queued", "running"):
                return True
    # Also treat copy dispatcher queue as busy via live import progress
    try:
        from neuraldisc.ingest.importer import list_live_imports

        for p in list_live_imports():
            if p.get("status") in ("queued", "running", "copying", "scanning"):
                return True
            if p.get("status") == "running" or p.get("phase") in (
                "copying",
                "scanning",
                "processing",
            ):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _has_live_job_type(live: set[str], job_type: str) -> bool:
    if not live:
        return False
    with session_scope() as session:
        for jid in live:
            job = session.get(Job, jid)
            if job and job.job_type == job_type and job.status in ("queued", "running"):
                return True
    return False


def _has_active_inference_job() -> bool:
    with session_scope() as session:
        return (
            session.query(Job.id)
            .filter(
                Job.job_type == "inference",
                Job.status.in_(("queued", "running")),
            )
            .first()
            is not None
        )


def _auto_resume_import(settings: Settings) -> str | None:
    """Resume the best interrupted/failed import that still has work."""
    with session_scope() as session:
        # Prefer interrupted (api_restart) over failed; skip user-cancel
        candidates = (
            session.query(Job)
            .filter(
                Job.job_type == "import",
                Job.status.in_(("interrupted", "failed")),
            )
            .order_by(Job.finished_at.desc().nullslast(), Job.created_at.desc())
            .limit(20)
            .all()
        )
        staging_n = (
            session.query(MediaItem.id)
            .filter(MediaItem.lifecycle == "staging")
            .count()
        )

        chosen: Job | None = None
        for job in candidates:
            if job.error in ("cancelled_by_user",):
                continue
            msg = (job.message or "").lower()
            if "cancelled by user" in msg or "cancelled_by_user" in (job.error or ""):
                continue
            # Work remaining: staging files OR payload still has sources
            has_payload = False
            try:
                payload = json.loads(job.payload or "{}")
                sources = payload.get("sources") or []
                has_payload = bool(sources)
            except Exception:  # noqa: BLE001
                has_payload = False
            if staging_n > 0 or has_payload:
                chosen = job
                break

        if chosen is None:
            # Staging orphans without a job — still drained by processor
            return None
        job_id = chosen.id

    from neuraldisc.ingest.importer import resume_import

    log.info("auto_resume_import", job_id=job_id, staging=staging_n)
    return resume_import(job_id, settings=settings)


def _auto_resume_post_ingest() -> str | None:
    with session_scope() as session:
        job = (
            session.query(Job)
            .filter(
                Job.job_type == "post_ingest",
                Job.status.in_(("interrupted", "failed")),
            )
            .order_by(Job.finished_at.desc().nullslast())
            .first()
        )
        if not job or job.error == "cancelled_by_user":
            return None
        try:
            payload = json.loads(job.payload or "{}")
        except Exception:  # noqa: BLE001
            return None
        disc_id = payload.get("disc_id")
        if not disc_id:
            return None
        job_id = job.id
        job.status = "queued"
        job.error = None
        job.finished_at = None
        job.message = "Auto-resume post-ingest"
        # commit via session_scope

    import threading

    from neuraldisc.jobs.control import clear_cancel, register_job
    from neuraldisc.processing.pipeline import process_disc

    clear_cancel(job_id)
    register_job(job_id)

    def _run() -> None:
        try:
            process_disc(disc_id, job_id=job_id)
        finally:
            clear_cancel(job_id)

    threading.Thread(
        target=_run, name=f"auto-post-{job_id[:8]}", daemon=True
    ).start()
    log.info("auto_resume_post_ingest", job_id=job_id, disc_id=disc_id)
    return job_id


def _is_heuristic(model_name: str | None) -> bool:
    m = (model_name or "").lower()
    return "heuristic" in m or m in ("quality-gate", "none", "")


def _collect_inference_ids(limit: int, *, force_heuristic: bool) -> list[str]:
    """Library items missing analysis or stuck on heuristic fallback."""
    with session_scope() as session:
        items = (
            session.query(MediaItem)
            .options(joinedload(MediaItem.analysis))
            .filter(MediaItem.lifecycle == "library")
            .order_by(MediaItem.created_at.asc())
            .limit(limit * 4)
            .all()
        )
        ids: list[str] = []
        for m in items:
            if m.analysis is None:
                ids.append(m.id)
            elif force_heuristic and _is_heuristic(m.analysis.model_name):
                ids.append(m.id)
            if len(ids) >= limit:
                break
        return ids


def _auto_start_inference(settings: Settings) -> int:
    """Start a background inference batch if the queue is non-empty."""
    global _LAST_INFERENCE_AUTO
    now = time.time()
    if now - _LAST_INFERENCE_AUTO < _INFERENCE_COOLDOWN_SEC:
        return 0

    force = True  # upgrade heuristics + missing analysis
    ids = _collect_inference_ids(
        settings.auto_resume_inference_limit, force_heuristic=force
    )
    if not ids:
        return 0

    import threading

    from neuraldisc.api.routes.inference import _run_inference_job
    from neuraldisc.jobs.control import register_job

    with session_scope() as session:
        job = Job(
            job_type="inference",
            status="queued",
            message=f"Auto-resume inference: {len(ids)} items",
            total=len(ids),
            completed=0,
            progress=0.0,
            payload=json.dumps(
                {
                    "media_ids": ids,
                    "force_heuristic": force,
                    "auto_resume": True,
                }
            ),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    register_job(job_id)
    _LAST_INFERENCE_AUTO = now
    threading.Thread(
        target=_run_inference_job,
        args=(job_id, ids),
        name=f"auto-infer-{job_id[:8]}",
        daemon=True,
    ).start()
    log.info("auto_resume_inference", job_id=job_id, n=len(ids))
    return len(ids)
