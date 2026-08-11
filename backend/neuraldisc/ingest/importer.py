"""High-throughput media importer — copy-first for fast disc rotation.

SOTA pipeline (default ``import_copy_only=True``):

  1. Scan source(s) + pre-filter junk (quality gates)
  2. Parallel COPY into library/staging/{provenance}/  (temp on target SSD)
  3. Import job **completes** when copy finishes → eject / next disc
  4. Global staging processor (separate threads) does EXIF / VLM / promote
     without touching the optical drive or blocking the next copy

Copy jobs run **serially** (``import_copy_serial``) so one disc is fully
copied before the next starts. Process never shares workers with copy.

Legacy mode (``import_copy_only=False``): copy + process pipelined per file.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from uuid import uuid4

from neuraldisc.config import Settings, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Disc, HitlQueueItem, Job, MediaItem
from neuraldisc.ingest.detector import probe_volume
from neuraldisc.ingest.extractor import (
    copy_with_sha256,
    make_provenance_name,
    media_type_for,
)
from neuraldisc.processing.pipeline import process_media_item
from neuraldisc.processing.quality import evaluate_path
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# In-process registry of live import jobs (progress detail beyond DB)
_LIVE: dict[str, "ImportProgress"] = {}
_LIVE_LOCK = threading.Lock()
_PROG_LOCK = threading.Lock()
# Serialize short SQLite writes from copy workers (process holds long VLM txs)
_DB_WRITE_LOCK = threading.Lock()

# Serial copy queue — one disc at a time for optical rotation
_COPY_QUEUE: Queue[tuple[str, list["ImportSource"], Settings, bool] | None] = Queue()
_COPY_DISPATCHER: threading.Thread | None = None
_COPY_DISPATCHER_LOCK = threading.Lock()


@dataclass
class ImportSource:
    path: Path
    name: str | None = None
    mode: str = "folder"  # disc | media | folder


@dataclass
class ImportProgress:
    job_id: str
    status: str = "queued"  # queued|scanning|copying|processing|completed|failed|cancelled
    phase: str = "queued"
    total: int = 0
    copied: int = 0
    processed: int = 0
    promoted: int = 0
    rejected: int = 0
    errors: int = 0
    skipped: int = 0  # already in library (resume)
    bytes_copied: int = 0
    sources_done: int = 0
    sources_total: int = 0
    message: str = ""
    disc_ids: list[str] = field(default_factory=list)
    reject_samples: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    cancel_requested: bool = False
    resume_of: str | None = None

    # True when this job only copies (process runs globally)
    copy_only: bool = True
    # Disc ready to eject (copy finished for this job)
    disc_ready: bool = False

    @property
    def items_per_hour(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        elapsed = max(end - self.started_at, 0.001)
        # Throughput of this phase: copy rate when copy_only, else promote rate
        done = self.copied if self.copy_only else (self.promoted + self.rejected)
        return done * 3600.0 / elapsed

    library_root: str = ""
    staging_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "phase": self.phase,
            "total": self.total,
            "copied": self.copied,
            "processed": self.processed,
            "promoted": self.promoted,
            "rejected": self.rejected,
            "errors": self.errors,
            "skipped": self.skipped,
            "bytes_copied": self.bytes_copied,
            "sources_done": self.sources_done,
            "sources_total": self.sources_total,
            "message": self.message,
            "disc_ids": list(self.disc_ids),
            "reject_samples": list(self.reject_samples)[:30],
            "items_per_hour": round(self.items_per_hour, 1),
            "error": self.error,
            "library_root": self.library_root,
            "staging_dir": self.staging_dir,
            "cancel_requested": self.cancel_requested,
            "resume_of": self.resume_of,
            "copy_only": self.copy_only,
            "disc_ready": self.disc_ready,
        }


def get_import_progress(job_id: str) -> ImportProgress | None:
    with _LIVE_LOCK:
        return _LIVE.get(job_id)


def list_live_imports() -> list[dict[str, Any]]:
    with _LIVE_LOCK:
        return [p.to_dict() for p in _LIVE.values()]


def mark_import_cancelled(job_id: str) -> bool:
    """Flag a live import for cooperative cancel. Returns True if found."""
    with _LIVE_LOCK:
        p = _LIVE.get(job_id)
        if not p:
            return False
        p.cancel_requested = True
        if p.status not in ("completed", "failed", "cancelled"):
            p.message = "Cancelling…"
            p.phase = "cancelling"
        return True


def _cancelled(progress: ImportProgress) -> bool:
    if progress.cancel_requested:
        return True
    from neuraldisc.jobs.control import is_cancel_requested

    if is_cancel_requested(progress.job_id):
        progress.cancel_requested = True
        return True
    return False


def _ensure_copy_dispatcher() -> None:
    """One thread drains the serial copy queue."""
    global _COPY_DISPATCHER
    with _COPY_DISPATCHER_LOCK:
        if _COPY_DISPATCHER is not None and _COPY_DISPATCHER.is_alive():
            return
        _COPY_DISPATCHER = threading.Thread(
            target=_copy_dispatcher_loop,
            name="neuraldisc-copy-dispatcher",
            daemon=True,
        )
        _COPY_DISPATCHER.start()
        log.info("copy_dispatcher_started")


def _copy_dispatcher_loop() -> None:
    while True:
        item = _COPY_QUEUE.get()
        if item is None:
            _COPY_QUEUE.task_done()
            break
        job_id, sources, settings, resume = item
        try:
            _run_import(job_id, sources, settings, resume=resume)
        except Exception as exc:  # noqa: BLE001
            log.exception("copy_job_crashed", job_id=job_id, error=str(exc))
        finally:
            _COPY_QUEUE.task_done()


def start_import(
    sources: list[ImportSource],
    *,
    settings: Settings | None = None,
) -> str:
    """Create job row and enqueue for serial copy. Returns job_id.

    With ``import_copy_only`` (default), the job finishes when files are on
    staging — classification continues on the global staging processor.
    """
    settings = settings or get_settings()
    settings.ensure_layout()

    with session_scope() as session:
        job = Job(
            job_type="import",
            status="queued",
            message=(
                "Queued for copy (serial disc queue)…"
                if settings.import_copy_serial
                else "Import queued"
            ),
            payload=json.dumps(
                {
                    "sources": [
                        {"path": str(s.path), "name": s.name, "mode": s.mode} for s in sources
                    ],
                    "copy_only": settings.import_copy_only,
                }
            ),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    from neuraldisc.jobs.control import register_job

    register_job(job_id)

    progress = ImportProgress(
        job_id=job_id,
        sources_total=len(sources),
        library_root=str(settings.library_root),
        staging_dir=str(settings.staging_dir),
        copy_only=settings.import_copy_only,
        message=(
            "Queued — waiting for previous disc copy…"
            if settings.import_copy_serial
            else "Import queued"
        ),
    )
    with _LIVE_LOCK:
        _LIVE[job_id] = progress

    # Ensure background process drain is alive (does not block copy)
    try:
        from neuraldisc.ingest.staging_processor import ensure_processor_running

        ensure_processor_running(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("staging_processor_start_failed", error=str(exc))

    if settings.import_copy_serial:
        _ensure_copy_dispatcher()
        _COPY_QUEUE.put((job_id, sources, settings, False))
        log.info(
            "import_enqueued",
            job_id=job_id,
            sources=len(sources),
            queue_depth=_COPY_QUEUE.qsize(),
            copy_only=settings.import_copy_only,
        )
    else:
        t = threading.Thread(
            target=_run_import,
            args=(job_id, sources, settings),
            name=f"neuraldisc-import-{job_id[:8]}",
            daemon=True,
        )
        t.start()
    return job_id


class ImportCancelled(Exception):
    """Raised when an import job is cancelled by the user."""


def resume_import(job_id: str, *, settings: Settings | None = None) -> str:
    """Resume an interrupted/failed/cancelled import job.

    1. Process remaining ``lifecycle=staging`` items (file already on disk)
    2. Re-scan original sources, skip files whose SHA-256 is already in the DB
    3. Reuse existing disc rows when source_path matches

    Returns the same ``job_id`` (re-activated).
    """
    settings = settings or get_settings()
    settings.ensure_layout()

    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job:
            raise ValueError("Job not found")
        if job.job_type != "import":
            raise ValueError("Only import jobs can be resumed via resume_import")
        if job.status in ("running", "queued"):
            # Allow resume only if no live worker
            from neuraldisc.jobs.control import live_worker_ids

            if job_id in live_worker_ids():
                raise ValueError("Job is still running")
        if job.status not in (
            "interrupted",
            "failed",
            "cancelled",
            "running",
            "queued",
        ):
            raise ValueError(f"Job status {job.status} is not resumable")

        try:
            payload = json.loads(job.payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        sources_raw = payload.get("sources") or []
        if not sources_raw:
            raise ValueError("Job has no sources in payload — cannot resume")

        sources = [
            ImportSource(
                path=Path(s["path"]),
                name=s.get("name"),
                mode=s.get("mode") or "folder",
            )
            for s in sources_raw
        ]
        # Reset job row
        job.status = "queued"
        job.error = None
        job.finished_at = None
        job.message = "Resume queued"
        job.progress = 0.0
        # keep completed/total as historical; will update as we go
        payload["resume_count"] = int(payload.get("resume_count") or 0) + 1
        payload["resumed_at"] = datetime.now(timezone.utc).isoformat()
        job.payload = json.dumps(payload)
        session.flush()

    from neuraldisc.jobs.control import clear_cancel, register_job

    clear_cancel(job_id)
    register_job(job_id)

    progress = ImportProgress(
        job_id=job_id,
        sources_total=len(sources),
        library_root=str(settings.library_root),
        staging_dir=str(settings.staging_dir),
        resume_of=job_id,
        copy_only=settings.import_copy_only,
    )
    with _LIVE_LOCK:
        _LIVE[job_id] = progress

    try:
        from neuraldisc.ingest.staging_processor import ensure_processor_running, wake_processor

        ensure_processor_running(settings)
        wake_processor()
    except Exception as exc:  # noqa: BLE001
        log.warning("staging_processor_start_failed", error=str(exc))

    if settings.import_copy_serial:
        _ensure_copy_dispatcher()
        _COPY_QUEUE.put((job_id, sources, settings, True))
    else:
        t = threading.Thread(
            target=_run_import,
            args=(job_id, sources, settings),
            kwargs={"resume": True},
            name=f"neuraldisc-resume-{job_id[:8]}",
            daemon=True,
        )
        t.start()
    log.info("import_resume_started", job_id=job_id, sources=len(sources))
    return job_id


def _run_import(
    job_id: str,
    sources: list[ImportSource],
    settings: Settings,
    *,
    resume: bool = False,
) -> None:
    progress = get_import_progress(job_id)
    assert progress is not None
    progress.status = "running"
    progress.phase = "scanning"
    progress.started_at = time.time()
    progress.message = "Resuming…" if resume else "Scanning sources…"
    _sync_job(job_id, progress)

    try:
        from neuraldisc.processing.metadata import require_exiftool

        require_exiftool()  # hard fail import if missing
        # All temp/staging MUST be on the configured target library volume
        settings.ensure_layout()
        settings.assert_on_target(settings.staging_dir, label="staging")
        settings.assert_on_target(settings.quarantine_dir, label="quarantine")
        settings.assert_on_target(settings.originals_dir, label="originals")
        log.info(
            "import_storage_on_target",
            library_root=str(settings.library_root),
            staging=str(settings.staging_dir),
            originals=str(settings.originals_dir),
            resume=resume,
        )

        copy_only = settings.import_copy_only
        progress.copy_only = copy_only

        # Resume + copy_only: leftover staging is the global processor's job
        if resume and not copy_only:
            progress.phase = "processing"
            progress.message = "Processing leftover staging files…"
            _sync_job(job_id, progress)
            _process_all_staging(settings, progress)
            if _cancelled(progress):
                raise ImportCancelled()
        elif resume and copy_only:
            from neuraldisc.ingest.staging_processor import wake_processor

            wake_processor()
            progress.message = "Resume: process queue woken · copying remaining sources…"
            _sync_job(job_id, progress)

        for src in sources:
            if _cancelled(progress):
                raise ImportCancelled()
            _import_one_source(
                src,
                settings,
                progress,
                skip_existing=resume,
                copy_only=copy_only,
            )
            progress.sources_done += 1
            _sync_job(job_id, progress)
            if _cancelled(progress):
                raise ImportCancelled()

        # Kick (or keep) background processor — never wait on VLM here
        try:
            from neuraldisc.ingest.staging_processor import wake_processor

            wake_processor()
        except Exception as wake_exc:  # noqa: BLE001
            log.warning("wake_processor_failed", error=str(wake_exc))

        if not copy_only:
            # Legacy: organise after inline process
            try:
                from neuraldisc.processing.organisation import auto_organise

                with session_scope() as session:
                    org = auto_organise(session, min_members=2)
                log.info("post_import_organise", **org.as_dict())
            except Exception as org_exc:  # noqa: BLE001
                log.warning("post_import_organise_failed", error=str(org_exc))

        progress.status = "completed"
        progress.disc_ready = True
        progress.finished_at = time.time()
        if copy_only:
            progress.phase = "copied"
            progress.message = (
                f"Copy done: {progress.copied} files "
                f"({progress.skipped} skipped, {progress.errors} errors) · "
                f"~{progress.items_per_hour:.0f} copy/h · "
                f"eject disc OK · classification runs in background"
            )
        else:
            progress.phase = "done"
            progress.message = (
                f"Done: {progress.promoted} promoted, {progress.rejected} rejected, "
                f"{progress.skipped} skipped, {progress.errors} errors · "
                f"~{progress.items_per_hour:.0f} items/h"
            )
        _sync_job(job_id, progress, finished=True)
        log.info("import_complete", **progress.to_dict())
    except ImportCancelled:
        progress.status = "cancelled"
        progress.phase = "cancelled"
        progress.finished_at = time.time()
        progress.error = "cancelled_by_user"
        progress.message = (
            f"Cancelled: {progress.promoted} promoted, {progress.rejected} rejected, "
            f"{progress.copied} copied before stop"
        )
        _sync_job(job_id, progress, finished=True, cancelled=True)
        from neuraldisc.jobs.control import mark_cancelled

        mark_cancelled(job_id, progress.message)
        log.info("import_cancelled", job_id=job_id, **progress.to_dict())
    except Exception as exc:  # noqa: BLE001
        log.exception("import_failed", job_id=job_id)
        progress.status = "failed"
        progress.error = str(exc)
        progress.finished_at = time.time()
        progress.message = f"Import failed: {exc}"
        _sync_job(job_id, progress, finished=True, failed=True)
    finally:
        # Copy-only jobs never load VLM; processor releases between its batches
        if not settings.import_copy_only:
            try:
                from neuraldisc.ai.vlm import release_vlm

                rel = release_vlm(force=True)
                log.info("import_mlx_released", job_id=job_id, **rel)
            except Exception as rel_exc:  # noqa: BLE001
                log.warning("import_release_failed", error=str(rel_exc))
        from neuraldisc.jobs.control import clear_cancel

        clear_cancel(job_id)


def _process_all_staging(settings: Settings, progress: ImportProgress) -> None:
    """Process every media row still in staging (resume path)."""
    with session_scope() as session:
        ids = [
            r[0]
            for r in session.query(MediaItem.id)
            .filter(MediaItem.lifecycle == "staging")
            .order_by(MediaItem.created_at.asc())
            .all()
        ]
    if not ids:
        progress.message = "No staging files to finish"
        return
    progress.total = max(progress.total, len(ids))
    for mid in ids:
        if _cancelled(progress):
            return
        try:
            result = process_media_item(
                mid,
                settings,
                promote=settings.import_stage_until_classified,
            )
            with _PROG_LOCK:
                progress.processed += 1
                if result == "promoted":
                    progress.promoted += 1
                elif result == "rejected":
                    progress.rejected += 1
                elif result == "error":
                    progress.errors += 1
                progress.message = (
                    f"Staging drain: {progress.promoted} promoted · "
                    f"{progress.processed}/{len(ids)}"
                )
        except Exception as exc:  # noqa: BLE001
            with _PROG_LOCK:
                progress.errors += 1
            log.error("resume_staging_failed", media_id=mid, error=str(exc))
        _sync_job(progress.job_id, progress)


def _import_one_source(
    source: ImportSource,
    settings: Settings,
    progress: ImportProgress,
    *,
    skip_existing: bool = False,
    copy_only: bool = True,
) -> None:
    path = source.path.expanduser().resolve()
    if not path.exists():
        progress.errors += 1
        progress.message = f"Missing path: {path}"
        progress.reject_samples.append(f"missing: {path}")
        return

    name = source.name
    volume_uuid = None
    filesystem = None
    if source.mode == "disc" or str(path).startswith("/Volumes"):
        info = probe_volume(path if path.is_dir() else path.parent)
        name = name or info.name
        volume_uuid = info.volume_uuid
        filesystem = info.filesystem
    name = name or path.name
    when = datetime.now(timezone.utc)
    # Reuse existing disc for resume when same source_path
    disc_id: str | None = None
    if skip_existing:
        with session_scope() as session:
            existing = (
                session.query(Disc)
                .filter(Disc.source_path == str(path))
                .order_by(Disc.inserted_at.desc())
                .first()
            )
            if existing:
                disc_id = existing.id
                existing.status = "extracting"
                existing.notes = (existing.notes or "") + " · resume"
    if disc_id is None:
        provenance = make_provenance_name(name, when)
        with session_scope() as session:
            disc = Disc(
                volume_name=name,
                volume_uuid=volume_uuid,
                filesystem=filesystem,
                inserted_at=when,
                status="extracting",
                source_path=str(path),
                notes="import pipeline" + (" · resume" if skip_existing else ""),
            )
            session.add(disc)
            session.flush()
            disc_id = disc.id
        staging_root = settings.staging_dir / provenance
        originals_root = settings.originals_dir / provenance
    else:
        # Keep staging under a resume-specific subfolder to avoid name clashes
        provenance = make_provenance_name(name + "_resume", when)
        staging_root = settings.staging_dir / provenance
        originals_root = settings.originals_dir / Path(
            # Prefer existing originals parent if any library item exists
            provenance
        )
        with session_scope() as session:
            sample = (
                session.query(MediaItem)
                .filter(MediaItem.disc_id == disc_id, MediaItem.lifecycle == "library")
                .first()
            )
            if sample:
                originals_root = Path(sample.library_path).parent

    settings.assert_on_target(staging_root.parent, label="staging_dir")
    staging_root.mkdir(parents=True, exist_ok=True)
    originals_root.mkdir(parents=True, exist_ok=True)
    progress.message = f"Staging on target: {settings.staging_dir}"
    if disc_id not in progress.disc_ids:
        progress.disc_ids.append(disc_id)

    # --- Scan ---
    progress.phase = "scanning"
    progress.message = f"Scanning {name}…"
    candidates = _scan_candidates(path, source.mode)
    work: list[tuple[Path, str, str]] = []  # src, rel, media_type
    for src in candidates:
        mtype = media_type_for(src)
        try:
            rel = str(src.relative_to(path)) if path.is_dir() else src.name
        except ValueError:
            rel = src.name

        if settings.quality_enabled:
            verdict = evaluate_path(src, settings)
            if verdict.rejected:
                progress.rejected += 1
                sample = f"{src.name}: {verdict.code} — {verdict.reason}"
                if len(progress.reject_samples) < 40:
                    progress.reject_samples.append(sample)
                log.info("import_pre_reject", path=str(src), code=verdict.code)
                continue
        if mtype is None:
            continue
        work.append((src, rel, mtype))

    # Archives on disc (zip/tar/…) that contain photos/videos → expand on target SSD
    if settings.import_expand_archives:
        from neuraldisc.ingest.archives import (
            expand_archives_for_import,
            scan_archives,
        )

        archives = scan_archives(path, mode=source.mode)
        if archives:
            progress.message = (
                f"{name}: {len(work)} loose media · checking {len(archives)} archive(s)…"
            )
            _sync_job(progress.job_id, progress)
            if _cancelled(progress):
                raise ImportCancelled()

            def _arc_msg(msg: str) -> None:
                progress.message = f"{name}: {msg}"
                _sync_job(progress.job_id, progress)

            from_archives = expand_archives_for_import(
                archives,
                staging_root,
                settings=settings,
                source_root=path if path.is_dir() else path.parent,
                on_progress=_arc_msg,
            )
            # Quality-gate extracted files (same rules as loose media)
            for src, rel, mtype in from_archives:
                if settings.quality_enabled:
                    verdict = evaluate_path(src, settings)
                    if verdict.rejected:
                        progress.rejected += 1
                        sample = f"{Path(rel).name}: {verdict.code} — {verdict.reason}"
                        if len(progress.reject_samples) < 40:
                            progress.reject_samples.append(sample)
                        try:
                            src.unlink(missing_ok=True)
                        except OSError:
                            pass
                        continue
                work.append((src, rel, mtype))
            log.info(
                "import_archives",
                source=str(path),
                archives=len(archives),
                media_from_archives=len(from_archives),
                disc_id=disc_id,
            )

    progress.total += len(work)
    progress.message = f"{name}: {len(work)} files to import"
    log.info("import_scan", source=str(path), candidates=len(work), disc_id=disc_id)

    if _cancelled(progress):
        raise ImportCancelled()

    if not work:
        with session_scope() as session:
            disc = session.get(Disc, disc_id)
            if disc:
                disc.status = "processed"
                disc.extracted_at = datetime.now(timezone.utc)
                disc.notes = "0 files (all rejected or empty)"
        return

    # --- Parallel COPY to staging (temp). Process is optional / deferred. ---
    progress.phase = "copying"
    copy_workers = max(1, settings.import_copy_workers)
    # Inline process only when not copy_only (legacy path)
    process_workers = 0 if copy_only else max(1, settings.import_process_workers)
    process_q: Queue[str | None] = Queue(maxsize=max(process_workers, 1) * 4)
    stop_token = None

    def copy_one(item: tuple[int, Path, str, str]) -> tuple[str | None, str | None, int]:
        seq, src, rel, mtype = item
        if _cancelled(progress):
            return None, "cancelled", 0
        dest_name = f"{seq:04d}_{src.name}"
        staging_path = staging_root / dest_name
        try:
            digest, size = copy_with_sha256(src, staging_path)
            # Resume: skip exact duplicates already in the catalogue
            if skip_existing:
                with session_scope() as session:
                    already = (
                        session.query(MediaItem.id)
                        .filter(MediaItem.sha256 == digest)
                        .first()
                    )
                if already:
                    staging_path.unlink(missing_ok=True)
                    with _PROG_LOCK:
                        progress.skipped += 1
                        progress.message = (
                            f"{name}: skipped {progress.skipped} existing · "
                            f"copied {progress.copied}"
                        )
                    return None, "skip", size
            media_id = str(uuid4())
            # File is already on target staging; DB insert serialized + retried
            last_exc: Exception | None = None
            for attempt in range(8):
                try:
                    with _DB_WRITE_LOCK:
                        with session_scope() as session:
                            media = MediaItem(
                                id=media_id,
                                disc_id=disc_id,
                                original_path=rel,
                                library_path=str(staging_path),
                                filename=src.name,
                                media_type=mtype,
                                file_size=size,
                                sha256=digest,
                                hitl_status="accepted",
                                lifecycle="staging",
                            )
                            session.add(media)
                    last_exc = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    time.sleep(0.15 * (attempt + 1))
            if last_exc is not None:
                raise last_exc
            with _PROG_LOCK:
                progress.copied += 1
                progress.bytes_copied += size
                if copy_only:
                    progress.message = (
                        f"{name}: copied {progress.copied}/{len(work)} · "
                        f"staging only (process later) · "
                        f"~{progress.items_per_hour:.0f}/h"
                    )
                else:
                    progress.message = (
                        f"{name}: copied {progress.copied}/{progress.total} · "
                        f"processing queue…"
                    )
            return media_id, None, size
        except Exception as exc:  # noqa: BLE001
            with _PROG_LOCK:
                progress.errors += 1
            log.error("import_copy_failed", path=str(src), error=str(exc))
            staging_path.unlink(missing_ok=True)
            return None, str(exc), 0

    def process_worker() -> None:
        while True:
            try:
                media_id = process_q.get(timeout=0.5)
            except Empty:
                if _cancelled(progress):
                    while True:
                        try:
                            mid = process_q.get_nowait()
                        except Empty:
                            break
                        process_q.task_done()
                        if mid is stop_token:
                            return
                    return
                continue
            if media_id is stop_token:
                process_q.task_done()
                break
            if _cancelled(progress):
                process_q.task_done()
                continue
            try:
                assert media_id is not None
                result = process_media_item(
                    media_id,
                    settings,
                    promote=settings.import_stage_until_classified,
                    provenance=provenance,
                    originals_root=originals_root,
                )
                with _PROG_LOCK:
                    progress.processed += 1
                    if result == "promoted":
                        progress.promoted += 1
                    elif result == "rejected":
                        progress.rejected += 1
                    elif result == "error":
                        progress.errors += 1
                    progress.message = (
                        f"{name}: {progress.promoted} in library · "
                        f"{progress.rejected} rejected · "
                        f"~{progress.items_per_hour:.0f}/h"
                    )
            except Exception as exc:  # noqa: BLE001
                with _PROG_LOCK:
                    progress.errors += 1
                log.error("import_process_failed", media_id=media_id, error=str(exc))
            finally:
                process_q.task_done()

    processors: list[threading.Thread] = []
    if not copy_only:
        processors = [
            threading.Thread(target=process_worker, daemon=True, name=f"proc-{i}")
            for i in range(process_workers)
        ]
        for t in processors:
            t.start()

    indexed = [(i + 1, src, rel, mt) for i, (src, rel, mt) in enumerate(work)]
    with ThreadPoolExecutor(max_workers=copy_workers) as pool:
        futures = {pool.submit(copy_one, item): item for item in indexed}
        for fut in as_completed(futures):
            if _cancelled(progress):
                for f in futures:
                    f.cancel()
                break
            media_id, err, _size = fut.result()
            if media_id and not copy_only:
                process_q.put(media_id)
            # Wake global processor periodically so classify overlaps later discs
            if copy_only and media_id and progress.copied % 20 == 0:
                try:
                    from neuraldisc.ingest.staging_processor import wake_processor

                    wake_processor()
                except Exception:  # noqa: BLE001
                    pass
            if progress.copied % 5 == 0 or progress.copied == len(work):
                _sync_job(progress.job_id, progress)

    if _cancelled(progress):
        if not copy_only:
            for _ in processors:
                process_q.put(stop_token)
            for t in processors:
                t.join(timeout=30)
        raise ImportCancelled()

    if not copy_only:
        progress.phase = "processing"
        progress.message = f"{name}: finishing classification…"
        process_q.join()
        for _ in processors:
            process_q.put(stop_token)
        for t in processors:
            t.join(timeout=120)
        if _cancelled(progress):
            raise ImportCancelled()
    else:
        # Disc free — process continues elsewhere
        progress.disc_ready = True
        progress.message = (
            f"{name}: copy complete ({progress.copied} files) · "
            f"eject when ready · classify in background"
        )
        try:
            from neuraldisc.ingest.staging_processor import wake_processor

            wake_processor()
        except Exception:  # noqa: BLE001
            pass

    # Cleanup empty staging (only when everything promoted — rare mid-copy)
    try:
        if staging_root.exists() and not any(staging_root.rglob("*")):
            shutil.rmtree(staging_root, ignore_errors=True)
        elif staging_root.exists() and not copy_only:
            for p in sorted(staging_root.rglob("*"), reverse=True):
                if p.is_dir():
                    try:
                        p.rmdir()
                    except OSError:
                        pass
    except OSError:
        pass

    with session_scope() as session:
        disc = session.get(Disc, disc_id)
        if disc:
            if copy_only:
                # Still extracting from the library POV until promote finishes
                disc.status = "extracting"
                disc.extracted_at = datetime.now(timezone.utc)
                disc.notes = (
                    f"copied={progress.copied} skipped={progress.skipped} "
                    f"errors={progress.errors} · process deferred"
                )
            else:
                disc.status = "processed" if progress.errors == 0 else "error"
                disc.extracted_at = datetime.now(timezone.utc)
                disc.notes = (
                    f"promoted={progress.promoted} rejected={progress.rejected} "
                    f"errors={progress.errors}"
                )


def _scan_candidates(path: Path, mode: str) -> list[Path]:
    walk_exts = set()
    from neuraldisc.config import MEDIA_EXTENSIONS

    walk_exts |= set(MEDIA_EXTENSIONS)
    walk_exts |= {".svg", ".svgz", ".eps", ".ai", ".pdf", ".ico", ".icns", ".emf", ".wmf"}

    if path.is_file():
        return [path]
    if mode == "media" and path.is_dir():
        # Non-recursive single folder of media
        return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in walk_exts)
    # disc / folder / batch item: recursive
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in walk_exts)


def _sync_job(
    job_id: str,
    progress: ImportProgress,
    *,
    finished: bool = False,
    failed: bool = False,
    cancelled: bool = False,
) -> None:
    try:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if not job:
                return
            if cancelled:
                job.status = "cancelled"
            elif failed:
                job.status = "failed"
            elif finished:
                job.status = "completed"
            else:
                job.status = "running"
            job.total = progress.total
            if progress.copy_only:
                job.completed = progress.copied + progress.skipped
                job.progress = (
                    (progress.copied + progress.skipped) / max(progress.total, 1)
                    if progress.total
                    else (1.0 if finished else 0.0)
                )
            else:
                job.completed = progress.promoted + progress.rejected
                job.progress = (
                    (progress.promoted + progress.rejected) / max(progress.total, 1)
                    if progress.total
                    else (1.0 if finished else 0.0)
                )
            job.message = progress.message
            if progress.error:
                job.error = progress.error
            if progress.started_at and not job.started_at:
                job.started_at = datetime.fromtimestamp(progress.started_at, tz=timezone.utc)
            if finished:
                job.finished_at = datetime.now(timezone.utc)
            # embed live stats in payload
            try:
                payload = json.loads(job.payload or "{}")
            except json.JSONDecodeError:
                payload = {}
            payload["live"] = progress.to_dict()
            job.payload = json.dumps(payload)
    except Exception as exc:  # noqa: BLE001
        log.debug("job_sync_failed", error=str(exc))
