"""Global staging processor — decoupled from disc copy.

Copy jobs only land files in ``library/staging`` + thin DB rows.
This worker drains ``lifecycle=staging`` in the background:

  EXIF → derivatives → VLM (optional) → promote → originals

It never holds the optical drive and does not block the serial copy queue.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neuraldisc.config import Settings, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.models import MediaItem
from neuraldisc.processing.pipeline import process_media_item
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_LOCK = threading.Lock()
_STATE: "ProcessState | None" = None
_THREAD: threading.Thread | None = None
_WAKE = threading.Event()
_STOP = threading.Event()
# media_id → consecutive process failures (avoid infinite re-queue)
_FAIL_COUNTS: dict[str, int] = {}
_MAX_ITEM_FAILURES = 3


@dataclass
class ProcessState:
    """Live progress of the background staging drain."""

    status: str = "idle"  # idle|running|stopping
    pending: int = 0
    processing: int = 0
    promoted: int = 0
    rejected: int = 0
    errors: int = 0
    last_message: str = "Idle"
    last_media_id: str | None = None
    started_at: float | None = None
    session_promoted: int = 0
    session_rejected: int = 0
    session_errors: int = 0
    workers: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pending": self.pending,
            "processing": self.processing,
            "promoted_session": self.session_promoted,
            "rejected_session": self.session_rejected,
            "errors_session": self.session_errors,
            "last_message": self.last_message,
            "last_media_id": self.last_media_id,
            "workers": self.workers,
            "updated_at": self.updated_at,
        }


def get_process_state() -> dict[str, Any]:
    with _LOCK:
        if _STATE is None:
            return ProcessState().to_dict()
        return _STATE.to_dict()


def staging_pending_count() -> int:
    try:
        with session_scope() as session:
            return (
                session.query(MediaItem)
                .filter(MediaItem.lifecycle == "staging")
                .count()
            )
    except Exception:  # noqa: BLE001
        return 0


def wake_processor() -> None:
    """Signal the drain loop that new staging files may exist."""
    _WAKE.set()
    ensure_processor_running()


def ensure_processor_running(settings: Settings | None = None) -> None:
    """Start the global process worker thread if not already alive."""
    global _THREAD, _STATE
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        settings = settings or get_settings()
        _STOP.clear()
        if _STATE is None:
            _STATE = ProcessState(workers=max(1, settings.import_process_workers))
        _THREAD = threading.Thread(
            target=_process_loop,
            args=(settings,),
            name="neuraldisc-staging-processor",
            daemon=True,
        )
        _THREAD.start()
        log.info(
            "staging_processor_started",
            workers=settings.import_process_workers,
        )


def stop_processor(*, timeout: float = 5.0) -> None:
    """Best-effort stop (API shutdown)."""
    _STOP.set()
    _WAKE.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=timeout)


def _claim_staging_ids(limit: int) -> list[str]:
    """Fetch oldest staging media ids (no long transaction)."""
    with session_scope() as session:
        rows = (
            session.query(MediaItem.id)
            .filter(MediaItem.lifecycle == "staging")
            .order_by(MediaItem.created_at.asc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]


def _process_one(media_id: str, settings: Settings) -> str:
    from neuraldisc.db.database import is_sqlite_locked

    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            return process_media_item(
                media_id,
                settings,
                promote=settings.import_stage_until_classified,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_sqlite_locked(exc) and attempt < 4:
                log.warning(
                    "staging_sqlite_retry",
                    media_id=media_id,
                    attempt=attempt + 1,
                )
                time.sleep(0.2 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


def _mark_staging_failed(media_id: str, reason: str) -> None:
    """Park broken staging rows so they are not retried forever."""
    try:
        with session_scope() as session:
            media = session.get(MediaItem, media_id)
            if media and media.lifecycle == "staging":
                media.lifecycle = "error"
                media.hitl_status = "rejected"
                media.updated_at = datetime.now(timezone.utc)
                log.warning(
                    "staging_item_parked",
                    media_id=media_id,
                    reason=reason,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("staging_park_failed", media_id=media_id, error=str(exc))


def _process_loop(settings: Settings) -> None:
    global _STATE
    workers = max(1, settings.import_process_workers)
    claim = max(1, min(8, settings.import_process_claim)) if workers <= 1 else max(1, settings.import_process_claim)

    with _LOCK:
        if _STATE is None:
            _STATE = ProcessState()
        _STATE.workers = workers
        _STATE.status = "running"
        _STATE.started_at = time.time()
        _STATE.last_message = "Background processor ready"
        _STATE.updated_at = time.time()

    idle_ticks = 0
    while not _STOP.is_set():
        try:
            pending = staging_pending_count()
            with _LOCK:
                if _STATE:
                    _STATE.pending = pending
                    _STATE.updated_at = time.time()

            if pending == 0:
                idle_ticks += 1
                with _LOCK:
                    if _STATE:
                        _STATE.status = "idle"
                        _STATE.processing = 0
                        _STATE.last_message = "Staging empty — waiting for copy jobs"
                # Wait for wake or poll slowly
                _WAKE.wait(timeout=2.0 if idle_ticks < 5 else 8.0)
                _WAKE.clear()
                continue

            idle_ticks = 0
            ids = _claim_staging_ids(min(claim, pending))
            if not ids:
                time.sleep(0.5)
                continue

            with _LOCK:
                if _STATE:
                    _STATE.status = "running"
                    _STATE.processing = len(ids)
                    _STATE.last_message = f"Processing {len(ids)} staging file(s)…"
                    _STATE.updated_at = time.time()

            log.info("staging_batch_start", n=len(ids), pending=pending)

            # Process batch with bounded concurrency — copy jobs use other threads
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="stg-proc",
            ) as pool:
                futures = {
                    pool.submit(_process_one, mid, settings): mid for mid in ids
                }
                for fut in as_completed(futures):
                    if _STOP.is_set():
                        break
                    mid = futures[fut]
                    try:
                        result = fut.result()
                        if result == "error":
                            n = _FAIL_COUNTS.get(mid, 0) + 1
                            _FAIL_COUNTS[mid] = n
                            if n >= _MAX_ITEM_FAILURES:
                                _mark_staging_failed(mid, f"error x{n}")
                                _FAIL_COUNTS.pop(mid, None)
                        else:
                            _FAIL_COUNTS.pop(mid, None)
                        with _LOCK:
                            if _STATE:
                                if result == "promoted":
                                    _STATE.session_promoted += 1
                                elif result == "rejected":
                                    _STATE.session_rejected += 1
                                elif result == "error":
                                    _STATE.session_errors += 1
                                _STATE.last_media_id = mid
                                _STATE.last_message = (
                                    f"Last: {result} · "
                                    f"+{_STATE.session_promoted} library · "
                                    f"{_STATE.session_rejected} rejected"
                                )
                                _STATE.updated_at = time.time()
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "staging_item_failed",
                            media_id=mid,
                            error=str(exc),
                        )
                        n = _FAIL_COUNTS.get(mid, 0) + 1
                        _FAIL_COUNTS[mid] = n
                        if n >= _MAX_ITEM_FAILURES:
                            _mark_staging_failed(mid, str(exc))
                            _FAIL_COUNTS.pop(mid, None)
                        with _LOCK:
                            if _STATE:
                                _STATE.session_errors += 1
                                _STATE.last_message = f"Error on {mid[:8]}: {exc}"

            # Free VLM between batches so peer apps / next copy aren't starved
            try:
                from neuraldisc.ai.vlm import release_vlm

                release_vlm(force=True)
            except Exception as rel_exc:  # noqa: BLE001
                log.debug("staging_vlm_release_failed", error=str(rel_exc))

            # Refresh smart albums occasionally
            try:
                from neuraldisc.processing.organisation import auto_organise

                with session_scope() as session:
                    auto_organise(session, min_members=2)
            except Exception:  # noqa: BLE001
                pass

        except Exception as exc:  # noqa: BLE001
            log.exception("staging_processor_loop_error", error=str(exc))
            time.sleep(2.0)

    with _LOCK:
        if _STATE:
            _STATE.status = "stopped"
            _STATE.last_message = "Processor stopped"
            _STATE.updated_at = time.time()
    log.info("staging_processor_stopped")
