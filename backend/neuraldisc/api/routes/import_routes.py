"""High-throughput import API — disc / media folder / batch."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neuraldisc.ingest.detector import list_mounted_volumes
from neuraldisc.ingest.importer import (
    ImportSource,
    get_import_progress,
    list_live_imports,
    start_import,
)
from neuraldisc.utils.logging import get_logger

router = APIRouter(prefix="/api/import", tags=["import"])
log = get_logger(__name__)


class ImportSourceIn(BaseModel):
    path: str
    name: str | None = None
    mode: str = "folder"  # disc | media | folder


class ImportRequest(BaseModel):
    """Start an import job.

    mode:
      - disc: single optical/volume path (recursive)
      - media: single folder, non-recursive (loose files)
      - folder: recursive folder walk
      - batch: multiple sources in `sources`
    """

    mode: str = "disc"
    path: str | None = None
    volume_name: str | None = None
    sources: list[ImportSourceIn] = Field(default_factory=list)


class ImportStartResponse(BaseModel):
    job_id: str
    message: str
    sources: int


class ImportStatusResponse(BaseModel):
    job_id: str
    status: str
    phase: str
    total: int
    copied: int
    processed: int
    promoted: int
    rejected: int
    errors: int
    bytes_copied: int
    sources_done: int
    sources_total: int
    message: str
    disc_ids: list[str]
    reject_samples: list[str]
    items_per_hour: float
    error: str | None = None
    library_root: str | None = None
    staging_dir: str | None = None
    cancel_requested: bool = False


@router.post("", response_model=ImportStartResponse)
def start_import_job(body: ImportRequest) -> ImportStartResponse:
    sources: list[ImportSource] = []

    if body.mode == "batch":
        if not body.sources and body.path:
            # newline-separated paths in path field
            for line in body.path.splitlines():
                line = line.strip()
                if line:
                    sources.append(ImportSource(path=Path(line), mode="folder"))
        for s in body.sources:
            sources.append(
                ImportSource(
                    path=Path(s.path).expanduser(),
                    name=s.name,
                    mode=s.mode if s.mode in {"disc", "media", "folder"} else "folder",
                )
            )
    else:
        if not body.path:
            raise HTTPException(400, "path is required unless mode=batch with sources")
        mode = body.mode if body.mode in {"disc", "media", "folder"} else "folder"
        sources.append(
            ImportSource(
                path=Path(body.path).expanduser(),
                name=body.volume_name,
                mode=mode,
            )
        )

    if not sources:
        raise HTTPException(400, "No import sources provided")

    # Validate paths exist
    missing = [str(s.path) for s in sources if not s.path.expanduser().exists()]
    if missing:
        raise HTTPException(400, f"Path(s) not found: {', '.join(missing[:5])}")

    from neuraldisc.processing.metadata import exiftool_available

    if not exiftool_available():
        raise HTTPException(
            503,
            "exiftool is required for import. Install with: brew install exiftool",
        )

    from neuraldisc.config import get_settings

    cfg = get_settings()
    try:
        cfg.ensure_layout()
        cfg.assert_on_target(cfg.staging_dir, label="staging")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            400,
            f"Library target not ready for staging (set Settings → library folder "
            f"to your external SSD): {exc}",
        ) from exc

    job_id = start_import(sources)
    log.info("import_started", job_id=job_id, sources=len(sources), mode=body.mode)
    return ImportStartResponse(
        job_id=job_id,
        message=f"Import started for {len(sources)} source(s)",
        sources=len(sources),
    )


@router.get("/live", response_model=list[ImportStatusResponse])
def live_imports() -> list[dict]:
    return list_live_imports()


@router.get("/suggestions/volumes")
def import_volume_suggestions(
    count_media: bool = True,
) -> list[dict]:
    """Auto-detect mounted volumes suitable for full-disc import.

    Optical / ejectable media are listed first. Optional media file count
    helps the UI show how much content is on the disc.
    """
    from neuraldisc.ingest.detector import volume_to_dict

    volumes = list_mounted_volumes(count_media=count_media, media_count_limit=3000)
    return [volume_to_dict(v) for v in volumes]


@router.get("/{job_id}", response_model=ImportStatusResponse)
def import_status(job_id: str) -> dict:
    progress = get_import_progress(job_id)
    if not progress:
        # Fall back to DB job payload
        from neuraldisc.db.database import session_scope
        from neuraldisc.db.models import Job
        import json

        with session_scope() as session:
            job = session.get(Job, job_id)
            if not job:
                raise HTTPException(404, "Import job not found")
            live = {}
            try:
                live = json.loads(job.payload or "{}").get("live") or {}
            except json.JSONDecodeError:
                pass
            return {
                "job_id": job_id,
                "status": job.status,
                "phase": live.get("phase", job.status),
                "total": job.total,
                "copied": live.get("copied", 0),
                "processed": live.get("processed", job.completed),
                "promoted": live.get("promoted", 0),
                "rejected": live.get("rejected", 0),
                "errors": live.get("errors", 0),
                "bytes_copied": live.get("bytes_copied", 0),
                "sources_done": live.get("sources_done", 0),
                "sources_total": live.get("sources_total", 0),
                "message": job.message or "",
                "disc_ids": live.get("disc_ids", []),
                "reject_samples": live.get("reject_samples", []),
                "items_per_hour": live.get("items_per_hour", 0),
                "error": job.error,
            }
    return progress.to_dict()
